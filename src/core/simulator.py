from __future__ import annotations

import csv
import json
import logging
import math
import random
from collections import defaultdict
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from src.channel import ChannelModel, InFChannelModel, StubBlerChannelModel
from src.core.queue import PriorityQueues
from src.core.types import (
    AttemptRecord,
    FlowSpec,
    Packet,
    PacketRecord,
    ResourceConfig,
    RunMetrics,
    SimulationConfig,
)
from src.scheduler import StrictPriorityScheduler
from src.traffic import TrafficGenerator


logger = logging.getLogger(__name__)


class Simulator:
    """Arrival -> Queue -> Strict Priority -> Channel -> Demand-based bandwidth slicing."""

    def __init__(self, config: dict[str, Any], outputs_root: Path | None = None) -> None:
        self.raw_config = config
        sim_cfg = config.get("simulation", {})
        self.config = SimulationConfig(
            duration_slots=int(sim_cfg["duration_slots"]),
            slot_time_ms=int(sim_cfg["slot_time_ms"]),
            random_seed=int(sim_cfg["random_seed"]),
        )
        self.outputs_root = outputs_root or Path("outputs")

        self.flow_specs = self._parse_flow_specs(config)
        self.ue_count, self.ue_seed_mode = self._parse_ue_config(config)
        self.traffic_gen = TrafficGenerator(
            flow_specs=self.flow_specs,
            random_seed=self.config.random_seed,
            ue_count=self.ue_count,
            seed_mode=self.ue_seed_mode,
        )
        self.flow_ids = [flow.id for flow in self.flow_specs]
        self.queues = PriorityQueues()
        self.scheduler = StrictPriorityScheduler(self.queues)

        self.resource_config = self._parse_resource_config(config)
        self.channel = self._build_channel_model(config)
        self.retx_enabled, self.max_tx, self.retx_strategy = self._parse_retransmission_config(config)
        self._tx_rng = random.Random(self.config.random_seed)

    def run(self) -> RunMetrics:
        logger.info(
            "Starting simulation: slots=%s slot_time_ms=%s seed=%s ue_count=%s bandwidth_fraction=%.3f",
            self.config.duration_slots,
            self.config.slot_time_ms,
            self.config.random_seed,
            self.ue_count,
            self.resource_config.bandwidth_fraction,
        )
        if hasattr(self.channel, "mcs_mode") and hasattr(self.channel, "mcs_list"):
            mcs_mode = getattr(self.channel, "mcs_mode")
            target_bler = getattr(self.channel, "target_bler", None)
            mcs_list = getattr(self.channel, "mcs_list")
            logger.info("PHY config: mcs_mode=%s mcs_list=%s", mcs_mode, mcs_list)
            if mcs_mode == "AMC":
                logger.info("PHY config: target_bler=%s", target_bler)
            else:
                logger.info("PHY config: target_bler=%s (ignored because mcs_mode=%s)", target_bler, mcs_mode)

        total_arrivals = 0
        total_served = 0
        total_delivered = 0
        total_tx_attempts = 0
        total_success_bits = 0
        total_deadline_missed = 0
        total_dropped_deadline = 0
        total_dropped_max_tx = 0
        total_allocated_bandwidth_mhz_ms = 0.0
        queue_max_len = 0

        arrivals_by_flow = {flow_id: 0 for flow_id in self.flow_ids}
        arrivals_by_ue = {ue_id: 0 for ue_id in range(self.ue_count)}

        packets_by_id: dict[str, Packet] = {}
        attempts: list[AttemptRecord] = []

        tx_snr_samples: list[float] = []
        delivered_sojourns: list[float] = []
        delivered_waiting_times: list[float] = []
        mcs_counts: dict[str, int] = {mcs: 0 for mcs in self._mcs_efficiency_bpshz()}
        num_los = 0

        for slot_idx in range(self.config.duration_slots):
            t_ms = slot_idx * self.config.slot_time_ms

            dropped_packets = self.queues.drop_expired(t_ms)
            for pkt in dropped_packets:
                pkt.drop_reason = "deadline"
                pkt.outcome = "dropped_deadline"
                self._finalize_packet(pkt, float(t_ms))
                total_deadline_missed += 1
                total_dropped_deadline += 1

            arrivals = self.traffic_gen.pop_arrivals(t_ms)
            total_arrivals += len(arrivals)
            for packet in arrivals:
                packet.remaining_bits = max(1, packet.packet_size_bytes * 8)
                packet.start_tx_time_ms = None
                packet.finish_time_ms = None
                packet.tx_duration_ms = 0.0
                packet.outcome = "pending"
                packets_by_id[packet.packet_id] = packet
                self.queues.enqueue(packet)
                arrivals_by_flow[packet.flow_id] = arrivals_by_flow.get(packet.flow_id, 0) + 1
                arrivals_by_ue[packet.ue_id] = arrivals_by_ue.get(packet.ue_id, 0) + 1

            remaining_bw_mhz = self.resource_config.bandwidth_fraction * self._total_bandwidth_mhz()
            deferred_requeue: list[Packet] = []

            while remaining_bw_mhz > 1e-9:
                pkt = self.scheduler.select_packet()
                if pkt is None:
                    break

                total_served += 1
                total_tx_attempts += 1
                pkt.tx_count += 1
                pkt.last_tx_time_ms = t_ms
                if pkt.start_tx_time_ms is None:
                    pkt.start_tx_time_ms = float(t_ms)

                result = self.channel.is_success(pkt, t_ms, self._tx_rng)
                success = bool(result["success"])
                bler_value = float(result["bler"])
                snr_db = float(result["snr_db"])
                mcs = str(result["mcs"])
                is_los = bool(result["is_los"])

                eta = self._mcs_efficiency_bpshz()[mcs]
                bw_req_mhz = self._bandwidth_demand_mhz(pkt.remaining_bits, eta)
                allocated_bw_mhz = min(bw_req_mhz, remaining_bw_mhz)
                if allocated_bw_mhz <= 1e-9:
                    deferred_requeue.append(pkt)
                    break

                bits_budget = self._bits_for_allocated_bandwidth(allocated_bw_mhz, eta)
                bits_sent = 0

                pkt.last_mcs = mcs
                pkt.last_snr_db = snr_db
                pkt.last_bler = bler_value
                pkt.last_is_success = success
                pkt.last_is_los = is_los
                pkt.last_allocated_bandwidth_mhz = allocated_bw_mhz
                pkt.last_bits_sent = 0

                remaining_bw_mhz -= allocated_bw_mhz
                total_allocated_bandwidth_mhz_ms += allocated_bw_mhz * self.config.slot_time_ms
                tx_snr_samples.append(snr_db)
                mcs_counts[mcs] = mcs_counts.get(mcs, 0) + 1
                num_los += 1 if is_los else 0

                if success:
                    bits_sent = min(bits_budget, pkt.remaining_bits)
                    pkt.remaining_bits -= bits_sent
                    pkt.last_bits_sent = bits_sent
                    total_success_bits += bits_sent

                    if pkt.remaining_bits <= 0:
                        pkt.remaining_bits = 0
                        pkt.is_delivered = True
                        pkt.outcome = "delivered"
                        finish_time_ms = float(t_ms + self.config.slot_time_ms)
                        self._finalize_packet(pkt, finish_time_ms)
                        total_delivered += 1
                        delivered_waiting_times.append(self._waiting_time_ms(pkt))
                        delivered_sojourns.append(self._sojourn_time_ms(pkt))
                    else:
                        pkt.outcome = "partial_success_requeue"
                        deferred_requeue.append(pkt)
                else:
                    if (not self.retx_enabled) or pkt.tx_count >= self.max_tx:
                        pkt.drop_reason = "max_tx"
                        pkt.outcome = "dropped_max_tx"
                        self._finalize_packet(pkt, float(t_ms + self.config.slot_time_ms))
                        total_dropped_max_tx += 1
                    else:
                        if self.retx_strategy != "immediate":
                            raise ValueError(f"Unsupported retransmission strategy: {self.retx_strategy}")
                        pkt.outcome = "tx_fail_requeue"
                        deferred_requeue.append(pkt)

                attempts.append(
                    AttemptRecord(
                        packet_id=pkt.packet_id,
                        ue_id=pkt.ue_id,
                        flow_id=pkt.flow_id,
                        attempt_idx=pkt.tx_count,
                        slot_idx=slot_idx,
                        t_tx_start_ms=t_ms,
                        allocated_bandwidth_mhz=allocated_bw_mhz,
                        bits_sent=bits_sent,
                        remaining_bits_after=pkt.remaining_bits,
                        is_success=success,
                        mcs=mcs,
                        snr_db=snr_db,
                        bler=bler_value,
                        is_los=is_los,
                    )
                )

            for pkt in deferred_requeue:
                self.queues.enqueue(pkt)

            queue_max_len = max(queue_max_len, len(self.queues))

        sim_end_ms = float(self.config.duration_slots * self.config.slot_time_ms)
        for pkt in packets_by_id.values():
            if pkt.finish_time_ms is None and not pkt.is_delivered:
                pkt.drop_reason = "sim_end"
                pkt.outcome = "dropped_sim_end"
                self._finalize_packet(pkt, sim_end_ms)

        packet_records = self._build_packet_records(list(packets_by_id.values()))
        per_flow_kpis = self._build_group_kpis(packet_records, key_fn=lambda r: r.flow_id, sim_time_s=self._sim_time_s())
        per_ue_kpis = self._build_group_kpis(
            packet_records, key_fn=lambda r: str(r.ue_id), sim_time_s=self._sim_time_s()
        )

        total_failed = sum(1 for record in packet_records if record.outcome != "delivered")
        total_capacity_bits = self.resource_config.bandwidth_fraction * self._total_bandwidth_mhz() * 1e6 * self._sim_time_s()

        total_deadline_missed_packets = sum(1 for record in packet_records if record.is_deadline_missed)

        metrics = RunMetrics(
            total_slots=self.config.duration_slots,
            random_seed=self.config.random_seed,
            total_arrivals=total_arrivals,
            arrivals_by_flow=arrivals_by_flow,
            arrivals_by_ue=arrivals_by_ue,
            total_served=total_served,
            total_delivered=total_delivered,
            total_deadline_missed=total_deadline_missed_packets,
            total_dropped_deadline=total_dropped_deadline,
            total_dropped_max_tx=total_dropped_max_tx,
            total_tx_attempts=total_tx_attempts,
            total_success_bits=total_success_bits,
            delivered_rate=total_delivered / max(1, total_arrivals),
            deadline_miss_ratio=total_deadline_missed_packets / max(1, total_arrivals),
            avg_tx_per_delivered=total_tx_attempts / max(1, total_delivered),
            total_failed=total_failed,
            failure_rate_total=total_failed / max(1, total_arrivals),
            avg_waiting_ms=(sum(delivered_waiting_times) / len(delivered_waiting_times)) if delivered_waiting_times else 0.0,
            avg_sojourn_ms=(sum(delivered_sojourns) / len(delivered_sojourns)) if delivered_sojourns else 0.0,
            p95_sojourn_ms=self._percentile(delivered_sojourns, 95),
            p99_sojourn_ms=self._percentile(delivered_sojourns, 99),
            throughput_bps=total_success_bits / self._sim_time_s(),
            bandwidth_fraction=self.resource_config.bandwidth_fraction,
            effective_bandwidth_mhz=self.resource_config.bandwidth_fraction * self._total_bandwidth_mhz(),
            bandwidth_utilization=total_success_bits / max(1.0, total_capacity_bits),
            queue_max_len=queue_max_len,
            queue_size_by_priority_end=self.queues.size_by_priority(),
            mean_snr_db=(sum(tx_snr_samples) / len(tx_snr_samples)) if tx_snr_samples else 0.0,
            p05_snr_db=self._percentile(tx_snr_samples, 5),
            p50_snr_db=self._percentile(tx_snr_samples, 50),
            p95_snr_db=self._percentile(tx_snr_samples, 95),
            mcs_counts=mcs_counts,
            los_rate=num_los / max(1, total_tx_attempts),
            per_flow_kpis=per_flow_kpis,
            per_ue_kpis=per_ue_kpis,
            jain_fairness_throughput=self._jain_fairness(
                [float(values["throughput_bps"]) for values in per_ue_kpis.values()]
            ),
        )

        output_dir = self._prepare_output_dir()
        self._save_metrics(metrics, output_dir)
        self._save_packet_records(packet_records, output_dir)
        self._save_attempt_records(attempts, output_dir)
        self._save_kpis(metrics, output_dir)
        return metrics

    def _build_channel_model(self, config: dict[str, Any]) -> ChannelModel:
        link_cfg = dict(config.get("link", {}))
        geometry_cfg = dict(link_cfg.get("geometry", {}))
        geometry_cfg.setdefault("ue_count", self.ue_count)
        link_cfg["geometry"] = geometry_cfg

        model = str(link_cfg.get("model", "stub_bler"))
        if model == "stub_bler":
            bler_by_flow_cfg = link_cfg.get("bler_by_flow", {})
            bler_by_flow = {str(k): float(v) for k, v in bler_by_flow_cfg.items()}
            default_bler = float(link_cfg.get("default_bler", 0.0))
            return StubBlerChannelModel(bler_by_flow=bler_by_flow, default_bler=default_bler)
        if model == "inf_channel":
            return InFChannelModel(link_cfg)
        raise ValueError(f"Unsupported link model: {model}")

    def _parse_retransmission_config(self, config: dict[str, Any]) -> tuple[bool, int, str]:
        retx_cfg = config.get("retransmission", {})
        enabled = bool(retx_cfg.get("enabled", True))
        max_tx = int(retx_cfg.get("max_tx", 1))
        strategy = str(retx_cfg.get("strategy", "immediate"))
        if max_tx < 1:
            raise ValueError("retransmission.max_tx must be >= 1")
        return enabled, max_tx, strategy

    def _parse_resource_config(self, config: dict[str, Any]) -> ResourceConfig:
        resource_cfg = config.get("resource", {})
        link_resource_cfg = config.get("link", {}).get("resource", {})
        min_share_cfg = resource_cfg.get("min_share", {})
        fraction = float(link_resource_cfg.get("bandwidth_fraction", 0.8))
        if not (0.0 < fraction <= 1.0):
            raise ValueError("link.resource.bandwidth_fraction must be in (0, 1]")
        return ResourceConfig(
            granularity=str(resource_cfg.get("granularity", "continuous")),
            allocation_policy=str(resource_cfg.get("allocation_policy", "demand_based")),
            bandwidth_fraction=fraction,
            min_share_enabled=bool(min_share_cfg.get("enabled", False)),
            min_share_per_priority_mhz={int(k): float(v) for k, v in min_share_cfg.get("per_priority_mhz", {}).items()},
            min_share_per_priority_fraction={
                int(k): float(v) for k, v in min_share_cfg.get("per_priority_fraction", {}).items()
            },
        )

    def _parse_ue_config(self, config: dict[str, Any]) -> tuple[int, str]:
        ue_cfg = config.get("traffic", {}).get("ue", {})
        ue_count = int(ue_cfg.get("count", 10))
        seed_mode = str(ue_cfg.get("seed_mode", "per_ue_offset"))
        if ue_count < 1:
            raise ValueError("traffic.ue.count must be >= 1")
        return ue_count, seed_mode

    def _mcs_efficiency_bpshz(self) -> dict[str, float]:
        link_cfg = self.raw_config.get("link", {})
        mcs_efficiency_cfg = link_cfg.get("mcs_efficiency_bpshz", {"QPSK": 1.0, "16QAM": 3.0})
        return {str(k): float(v) for k, v in mcs_efficiency_cfg.items()}

    def _bandwidth_demand_mhz(self, remaining_bits: int, spectral_efficiency_bpshz: float) -> float:
        slot_time_s = self.config.slot_time_ms / 1000.0
        return remaining_bits / max(1e-12, slot_time_s * spectral_efficiency_bpshz * 1e6)

    def _bits_for_allocated_bandwidth(self, allocated_bw_mhz: float, spectral_efficiency_bpshz: float) -> int:
        slot_time_s = self.config.slot_time_ms / 1000.0
        bits = math.floor(allocated_bw_mhz * 1e6 * spectral_efficiency_bpshz * slot_time_s)
        return max(1, bits)

    def _build_packet_records(self, packets: list[Packet]) -> list[PacketRecord]:
        records: list[PacketRecord] = []
        for pkt in packets:
            finish_time_ms = pkt.finish_time_ms
            is_deadline_missed = pkt.outcome == "dropped_deadline"
            if finish_time_ms is not None and pkt.outcome != "dropped_deadline":
                is_deadline_missed = (finish_time_ms - pkt.arrival_time_ms) > pkt.deadline_ms

            records.append(
                PacketRecord(
                    packet_id=pkt.packet_id,
                    ue_id=pkt.ue_id,
                    flow_id=pkt.flow_id,
                    flow_type=pkt.flow_type,
                    priority=pkt.priority,
                    size_bytes=pkt.packet_size_bytes,
                    arrival_time_ms=pkt.arrival_time_ms,
                    start_tx_time_ms=pkt.start_tx_time_ms,
                    finish_time_ms=finish_time_ms,
                    tx_duration_ms=pkt.tx_duration_ms,
                    deadline_ms=pkt.deadline_ms,
                    outcome=pkt.outcome if pkt.outcome else "pending_end",
                    tx_count=pkt.tx_count,
                    is_deadline_missed=is_deadline_missed,
                    mcs=pkt.last_mcs,
                    snr_db=pkt.last_snr_db,
                    bler=pkt.last_bler,
                )
            )
        records.sort(key=lambda r: (r.arrival_time_ms, r.priority, r.ue_id, r.packet_id))
        return records

    def _build_group_kpis(
        self,
        packet_records: list[PacketRecord],
        key_fn,
        sim_time_s: float,
    ) -> dict[str, dict[str, float]]:
        grouped: dict[str, list[PacketRecord]] = defaultdict(list)
        for record in packet_records:
            grouped[str(key_fn(record))].append(record)

        result: dict[str, dict[str, float]] = {}
        for key, records in grouped.items():
            delivered = [r for r in records if r.outcome == "delivered" and r.finish_time_ms is not None]
            delivered_sojourns: list[float] = []
            for record in delivered:
                if record.finish_time_ms is None:
                    continue
                delivered_sojourns.append(record.finish_time_ms - record.arrival_time_ms)
            delivered_bits = sum(r.size_bytes * 8 for r in delivered)
            deadline_missed = sum(1 for r in records if r.is_deadline_missed)
            result[key] = {
                "delivery_ratio": len(delivered) / max(1, len(records)),
                "deadline_miss_ratio": deadline_missed / max(1, len(records)),
                "mean_sojourn_ms": (sum(delivered_sojourns) / len(delivered_sojourns)) if delivered_sojourns else 0.0,
                "p95_sojourn_ms": self._percentile(delivered_sojourns, 95),
                "p99_sojourn_ms": self._percentile(delivered_sojourns, 99),
                "throughput_bps": delivered_bits / sim_time_s,
                "bandwidth_utilization": delivered_bits / max(1.0, self.total_capacity_bits_for_sim()),
            }
        return result

    def total_capacity_bits_for_sim(self) -> float:
        return self.resource_config.bandwidth_fraction * self._total_bandwidth_mhz() * 1e6 * self._sim_time_s()

    def _finalize_packet(self, pkt: Packet, finish_time_ms: float) -> None:
        pkt.finish_time_ms = finish_time_ms
        if pkt.start_tx_time_ms is None:
            pkt.tx_duration_ms = 0.0
        else:
            pkt.tx_duration_ms = finish_time_ms - pkt.start_tx_time_ms

    def _waiting_time_ms(self, pkt: Packet) -> float:
        if pkt.start_tx_time_ms is None:
            return 0.0
        return pkt.start_tx_time_ms - pkt.arrival_time_ms

    def _sojourn_time_ms(self, pkt: Packet) -> float:
        if pkt.finish_time_ms is None:
            return 0.0
        return pkt.finish_time_ms - pkt.arrival_time_ms

    def _parse_flow_specs(self, config: dict[str, Any]) -> list[FlowSpec]:
        traffic_cfg = config.get("traffic", {})
        flows_cfg = traffic_cfg.get("flows", [])
        flow_specs: list[FlowSpec] = []
        for flow in flows_cfg:
            arrival_cfg = flow.get("arrival", {})
            flow_specs.append(
                FlowSpec(
                    id=str(flow["id"]),
                    type=str(flow["type"]),
                    arrival_model=str(arrival_cfg["model"]),
                    period_ms=(int(arrival_cfg["period_ms"]) if "period_ms" in arrival_cfg else None),
                    lambda_per_s=(float(arrival_cfg["lambda_per_s"]) if "lambda_per_s" in arrival_cfg else None),
                    packet_size_bytes=int(flow["packet_size_bytes"]),
                    deadline_ms=int(flow["deadline_ms"]),
                    priority=int(flow["priority"]),
                )
            )
        return flow_specs

    def _total_bandwidth_mhz(self) -> float:
        return float(self.raw_config.get("link", {}).get("scenario", {}).get("bandwidth_mhz", 20.0))

    def _sim_time_s(self) -> float:
        return max(1e-9, self.config.duration_slots * self.config.slot_time_ms / 1000.0)

    def _prepare_output_dir(self) -> Path:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_dir = self.outputs_root / timestamp
        output_dir.mkdir(parents=True, exist_ok=True)
        return output_dir

    def _save_metrics(self, metrics: RunMetrics, output_dir: Path) -> None:
        metrics_path = output_dir / "metrics.json"
        with metrics_path.open("w", encoding="utf-8") as f:
            json.dump(asdict(metrics), f, indent=2)

    def _save_kpis(self, metrics: RunMetrics, output_dir: Path) -> None:
        kpis_path = output_dir / "kpis.json"
        payload = {
            "per_flow": metrics.per_flow_kpis,
            "per_ue": metrics.per_ue_kpis,
            "jain_fairness_throughput": metrics.jain_fairness_throughput,
        }
        with kpis_path.open("w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)

    def _save_packet_records(self, records: list[PacketRecord], output_dir: Path) -> None:
        csv_path = output_dir / "packet_records.csv"
        fieldnames = [
            "packet_id",
            "ue_id",
            "flow_id",
            "flow_type",
            "priority",
            "size_bytes",
            "arrival_time_ms",
            "start_tx_time_ms",
            "finish_time_ms",
            "tx_duration_ms",
            "deadline_ms",
            "outcome",
            "tx_count",
            "is_deadline_missed",
            "mcs",
            "snr_db",
            "bler",
        ]
        with csv_path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for record in records:
                writer.writerow(asdict(record))

    def _save_attempt_records(self, attempts: list[AttemptRecord], output_dir: Path) -> None:
        csv_path = output_dir / "attempts.csv"
        fieldnames = [
            "packet_id",
            "ue_id",
            "flow_id",
            "attempt_idx",
            "slot_idx",
            "t_tx_start_ms",
            "allocated_bandwidth_mhz",
            "mcs",
            "snr_db",
            "bler",
            "is_success",
            "bits_sent",
            "remaining_bits_after",
            "is_los",
        ]
        with csv_path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for attempt in attempts:
                writer.writerow(asdict(attempt))

    def _percentile(self, values: list[float] | list[int], p: int) -> float:
        if not values:
            return 0.0
        sorted_values = sorted(float(v) for v in values)
        rank = max(1, (p * len(sorted_values) + 99) // 100)
        return float(sorted_values[min(rank - 1, len(sorted_values) - 1)])

    @staticmethod
    def _is_waiting_deadline_expired(waiting_ms: int, deadline_ms: int) -> bool:
        return waiting_ms >= deadline_ms

    @staticmethod
    def _is_served_deadline_missed(sojourn_ms: int, deadline_ms: int) -> bool:
        return sojourn_ms > deadline_ms

    @staticmethod
    def _jain_fairness(values: list[float]) -> float:
        positive = [v for v in values if v >= 0]
        if not positive:
            return 0.0
        numerator = sum(positive) ** 2
        denominator = len(positive) * sum(v * v for v in positive)
        if denominator <= 0:
            return 0.0
        return numerator / denominator
