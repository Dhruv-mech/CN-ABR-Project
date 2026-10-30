"""
Network Simulator Module.

Replays bandwidth variations over time using synthetic or real-world trace files (CSV).
This software simulator runs purely in Python on Windows, removing any need for
Mininet, Linux network namespaces, or root privileges.
"""

import csv
import math
import bisect
from pathlib import Path
from typing import List, Tuple, Optional, Union, Dict, Any


def load_trace_from_csv(file_path: Union[str, Path]) -> List[Tuple[float, float]]:
    """
    Loads timestamped bandwidth values from a CSV file.

    Expected CSV columns:
      - timestamp_sec (float >= 0, strictly increasing)
      - bandwidth_mbps (float >= 0)

    Lines starting with '#' are treated as comments/metadata and ignored.

    Args:
        file_path: Path to the CSV trace file.

    Returns:
        List[Tuple[float, float]]: List of (timestamp_sec, bandwidth_kbps) entries.

    Raises:
        FileNotFoundError: If the file does not exist.
        ValueError: If headers are missing, data is non-numeric, bandwidth is negative,
                    or timestamps are not strictly increasing.
    """
    path = Path(file_path).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Trace CSV file not found: {path}")

    trace_samples: List[Tuple[float, float]] = []

    with open(path, mode="r", encoding="utf-8-sig") as csv_file:
        reader = csv.reader(csv_file)
        header_row = None
        line_num = 0

        # Scan for header while skipping comments and empty lines
        for raw_line in reader:
            line_num += 1
            if not raw_line:
                continue
            first_cell = raw_line[0].strip()
            if first_cell.startswith("#"):
                continue
            header_row = [cell.strip().lower() for cell in raw_line]
            break

        if header_row is None:
            raise ValueError(f"Trace file '{path.name}' is empty or contains no valid rows.")

        # Identify required columns (supporting standard names and common aliases)
        time_idx = -1
        bw_idx = -1

        for idx, col in enumerate(header_row):
            if col in ("timestamp_sec", "timestamp", "time_sec", "time"):
                time_idx = idx
            elif col in ("bandwidth_mbps", "bandwidth", "bw_mbps"):
                bw_idx = idx

        if time_idx == -1 or bw_idx == -1:
            raise ValueError(
                f"Missing required CSV columns in '{path.name}'. "
                f"Found: {header_row}. Expected 'timestamp_sec' and 'bandwidth_mbps'."
            )

        last_timestamp: Optional[float] = None

        # Parse data rows
        for raw_line in reader:
            line_num += 1
            if not raw_line or raw_line[0].strip().startswith("#"):
                continue

            if len(raw_line) <= max(time_idx, bw_idx):
                raise ValueError(
                    f"Line {line_num} in '{path.name}' has fewer columns than expected: {raw_line}"
                )

            # Validate numeric conversion
            try:
                t_val = float(raw_line[time_idx].strip())
                bw_mbps = float(raw_line[bw_idx].strip())
            except ValueError as e:
                raise ValueError(
                    f"Invalid non-numeric value on line {line_num} in '{path.name}': {e}"
                )

            if math.isnan(t_val) or math.isinf(t_val):
                raise ValueError(f"Timestamp cannot be NaN or Inf on line {line_num} in '{path.name}'.")
            if math.isnan(bw_mbps) or math.isinf(bw_mbps):
                raise ValueError(f"Bandwidth cannot be NaN or Inf on line {line_num} in '{path.name}'.")

            # Validate non-negative timestamp
            if t_val < 0.0:
                raise ValueError(
                    f"Negative timestamp ({t_val} s) found on line {line_num} in '{path.name}'."
                )

            # Validate non-negative bandwidth
            if bw_mbps < 0.0:
                raise ValueError(
                    f"Negative bandwidth ({bw_mbps} Mbps) found on line {line_num} in '{path.name}'."
                )

            # Validate strictly increasing timestamps
            if last_timestamp is not None and t_val <= last_timestamp:
                raise ValueError(
                    f"Timestamps must be strictly increasing. "
                    f"Found timestamp {t_val} <= {last_timestamp} on line {line_num} in '{path.name}'."
                )

            last_timestamp = t_val
            # Convert Mbps to kbps internally (1 Mbps = 1000 kbps)
            bw_kbps = bw_mbps * 1000.0
            trace_samples.append((t_val, bw_kbps))

    if not trace_samples:
        raise ValueError(f"Trace file '{path.name}' contains a header but no data rows.")

    return trace_samples


class NetworkSimulator:
    """
    Simulates dynamic network conditions by replaying time-varying bandwidth traces.

    Internally represents trace as a list of (timestamp_sec, bandwidth_kbps) entries.
    Lookups use step-wise zero-order hold (the bandwidth at sample t_k stays in effect
    until sample t_{k+1}).
    """

    def __init__(
        self,
        trace: Optional[List[Tuple[float, float]]] = None,
        latency_sec: float = 0.0,
        timeout_sec: float = 30.0,
    ):
        """
        Initialize the NetworkSimulator.

        Args:
            trace: List of (timestamp_sec, bandwidth_kbps). If None, defaults to 2500 kbps constant.
            latency_sec: Base RTT / propagation latency added to each download in seconds.
            timeout_sec: Maximum duration in seconds allowed before a download times out.
        """
        self.latency_sec = max(0.0, latency_sec)
        self.timeout_sec = max(0.1, timeout_sec)
        self.current_time_sec: float = 0.0

        if trace is not None:
            self.load_trace(trace)
        else:
            self.load_trace([(0.0, 2500.0)])

    @classmethod
    def from_csv(
        cls,
        file_path: Union[str, Path],
        latency_sec: float = 0.0,
        timeout_sec: float = 30.0,
    ) -> "NetworkSimulator":
        """
        Factory method to instantiate a NetworkSimulator from a CSV trace file.

        Args:
            file_path: Path to CSV trace file with columns 'timestamp_sec' and 'bandwidth_mbps'.
            latency_sec: Base propagation delay in seconds.
            timeout_sec: Download timeout limit in seconds.
        """
        samples = load_trace_from_csv(file_path)
        return cls(trace=samples, latency_sec=latency_sec, timeout_sec=timeout_sec)

    def load_trace(self, trace: List[Tuple[float, float]]) -> None:
        """Loads and sorts trace samples in kbps."""
        if not trace:
            raise ValueError("Trace sample list cannot be empty.")
        self.trace = sorted(trace, key=lambda x: x[0])
        self._timestamps = [sample[0] for sample in self.trace]

    def load_csv(self, file_path: Union[str, Path]) -> None:
        """Loads trace samples from a CSV file into the current simulator instance."""
        samples = load_trace_from_csv(file_path)
        self.load_trace(samples)

    def get_bandwidth_at(self, time_sec: float, unit: str = "kbps") -> float:
        """
        Returns the instantaneous bandwidth available at `time_sec`.

        Lookup rules:
          - Between samples (t_i <= time_sec < t_{i+1}): Step-wise constant (zero-order hold),
            returning the bandwidth of sample i.
          - Before first sample (time_sec < t_0): Clamped to the first sample's bandwidth.
          - After last sample (time_sec >= t_last): Clamped to the last sample's bandwidth.

        Args:
            time_sec: Simulation timestamp in seconds.
            unit: "kbps" (default) or "mbps".

        Returns:
            float: Bandwidth in the requested unit.
        """
        if not self.trace:
            return 1000.0 if unit == "kbps" else 1.0

        # bisect_right returns index where time_sec could be inserted while preserving order
        idx = bisect.bisect_right(self._timestamps, time_sec) - 1

        if idx < 0:
            bw_kbps = self.trace[0][1]
        elif idx >= len(self.trace):
            bw_kbps = self.trace[-1][1]
        else:
            bw_kbps = self.trace[idx][1]

        if unit.lower() == "mbps":
            return bw_kbps / 1000.0
        return bw_kbps

    def get_bandwidth_kbps(self, time_sec: float) -> float:
        """Convenience method returning bandwidth at time_sec in kbps."""
        return self.get_bandwidth_at(time_sec, unit="kbps")

    def get_bandwidth_mbps(self, time_sec: float) -> float:
        """Convenience method returning bandwidth at time_sec in Mbps."""
        return self.get_bandwidth_at(time_sec, unit="mbps")

    @staticmethod
    def estimate_download_time(
        segment_size_kb: float,
        bandwidth_kbps: float,
        latency_sec: float = 0.0,
        timeout_sec: Optional[float] = None,
    ) -> float:
        """
        Static analytical estimation of segment download duration.

        Formula:
          Duration = Latency + (Segment_Size / Bandwidth)

        Handles zero bandwidth safely: returns timeout_sec or float('inf').
        Never divides by zero or returns misleading negative/zero download times.

        Args:
            segment_size_kb: Size of video segment in kilobits.
            bandwidth_kbps: Available throughput in kbps.
            latency_sec: Base propagation delay in seconds.
            timeout_sec: Optional maximum cap on download duration.

        Returns:
            float: Estimated download duration in seconds.
        """
        if segment_size_kb < 0:
            raise ValueError(f"Segment size cannot be negative: {segment_size_kb}")
        if latency_sec < 0:
            raise ValueError(f"Latency cannot be negative: {latency_sec}")

        if segment_size_kb == 0.0:
            return latency_sec

        # Zero or negative bandwidth -> infinite or timeout duration
        if bandwidth_kbps <= 0.0:
            if timeout_sec is not None:
                return latency_sec + timeout_sec
            return float("inf")

        duration = latency_sec + (segment_size_kb / bandwidth_kbps)
        if timeout_sec is not None and duration > timeout_sec:
            return timeout_sec
        return duration

    def simulate_segment_download(
        self,
        segment_size_kb: float,
        dynamic: bool = True
    ) -> Tuple[float, float]:
        """
        Simulates downloading a video segment of given size (in kilobits).

        When dynamic=True, simulates downloading across time-varying trace samples
        (piecewise trace integration). If the bandwidth is zero or download exceeds
        timeout_sec, the transfer safely caps at timeout_sec without dividing by zero.

        Args:
            segment_size_kb: Video segment size in kilobits.
            dynamic: If True, integrates throughput across changing bandwidth samples.

        Returns:
            Tuple[float, float]: (download_time_sec, effective_throughput_kbps)
        """
        if segment_size_kb < 0:
            raise ValueError(f"Segment size cannot be negative: {segment_size_kb}")

        if segment_size_kb == 0.0:
            self.current_time_sec += self.latency_sec
            return self.latency_sec, self.get_bandwidth_at(self.current_time_sec)

        if not dynamic:
            # Simple instantaneous approximation
            bw = self.get_bandwidth_at(self.current_time_sec)
            download_time = self.estimate_download_time(
                segment_size_kb=segment_size_kb,
                bandwidth_kbps=bw,
                latency_sec=self.latency_sec,
                timeout_sec=self.timeout_sec,
            )
            self.current_time_sec += download_time
            effective_tp = bw if bw > 0 else 0.0
            return download_time, effective_tp

        # Piecewise dynamic simulation across changing trace intervals
        remaining_kb = segment_size_kb
        start_time = self.current_time_sec
        sim_time = self.current_time_sec + self.latency_sec

        while remaining_kb > 0.0:
            elapsed = sim_time - start_time
            if elapsed >= self.timeout_sec:
                self.current_time_sec = start_time + self.timeout_sec
                return self.timeout_sec, 0.0

            # Current bandwidth in this interval
            bw = self.get_bandwidth_at(sim_time, unit="kbps")

            # Determine time to next trace event
            idx = bisect.bisect_right(self._timestamps, sim_time)
            if idx < len(self._timestamps):
                dt_window = max(0.0, self._timestamps[idx] - sim_time)
            else:
                dt_window = float("inf")

            if bw <= 0.0:
                # Blackout / zero bandwidth
                if dt_window == float("inf") or (elapsed + dt_window) >= self.timeout_sec:
                    self.current_time_sec = start_time + self.timeout_sec
                    return self.timeout_sec, 0.0
                sim_time += dt_window
                continue

            # Bandwidth is positive
            if dt_window == float("inf"):
                time_needed = remaining_kb / bw
                if (elapsed + time_needed) > self.timeout_sec:
                    self.current_time_sec = start_time + self.timeout_sec
                    transferred = (self.timeout_sec - elapsed) * bw
                    total_transferred = (segment_size_kb - remaining_kb) + max(0.0, transferred)
                    net_trans_time = max(1e-6, self.timeout_sec - self.latency_sec)
                    return self.timeout_sec, total_transferred / net_trans_time
                sim_time += time_needed
                remaining_kb = 0.0
            else:
                capacity_in_window = bw * dt_window
                if remaining_kb <= capacity_in_window:
                    time_needed = remaining_kb / bw
                    if (elapsed + time_needed) > self.timeout_sec:
                        self.current_time_sec = start_time + self.timeout_sec
                        return self.timeout_sec, 0.0
                    sim_time += time_needed
                    remaining_kb = 0.0
                else:
                    remaining_kb -= capacity_in_window
                    sim_time += dt_window

        total_download_time = sim_time - start_time
        self.current_time_sec = sim_time
        transmission_time = max(1e-6, total_download_time - self.latency_sec)
        effective_throughput = segment_size_kb / transmission_time

        return total_download_time, effective_throughput

    def reset(self) -> None:
        """Resets the simulation clock to 0.0."""
        self.current_time_sec = 0.0
