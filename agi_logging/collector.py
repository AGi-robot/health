"""Persist ROS log events and broadcast them for other ROS systems."""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from logging.handlers import RotatingFileHandler

import rclpy
from rcl_interfaces.msg import Log
from rclpy.node import Node
from std_msgs.msg import String


class LogCollector(Node):
    """Collect /rosout records into rotating JSONL files and /agi/logs."""

    def __init__(self) -> None:
        super().__init__("agi_log_collector")
        self.declare_parameter("log_dir", os.getenv("AGI_LOG_DIR", "~/.agi/log"))
        self.declare_parameter("max_bytes", 10 * 1024 * 1024)
        self.declare_parameter("backup_count", 5)
        log_dir = Path(str(self.get_parameter("log_dir").value)).expanduser()
        log_dir.mkdir(parents=True, exist_ok=True)
        size = int(self.get_parameter("max_bytes").value)
        backups = int(self.get_parameter("backup_count").value)
        self._application = RotatingFileHandler(log_dir / "application.jsonl", maxBytes=size, backupCount=backups, encoding="utf-8")
        self._errors = RotatingFileHandler(log_dir / "errors.jsonl", maxBytes=size, backupCount=backups, encoding="utf-8")
        self._publisher = self.create_publisher(String, "/agi/logs", 100)
        self._subscription = self.create_subscription(Log, "/rosout", self._on_log, 100)

    def _on_log(self, message: Log) -> None:
        """Persist and broadcast one ROS log event without re-logging it."""
        stamp = message.stamp
        when = datetime.fromtimestamp(stamp.sec + stamp.nanosec / 1e9, timezone.utc).isoformat()
        event = {
            "timestamp": when,
            "level": {10: "DEBUG", 20: "INFO", 30: "WARN", 40: "ERROR", 50: "FATAL"}.get(message.level, str(message.level)),
            "node": message.name,
            "message": message.msg[:4000],
            "file": message.file,
            "function": message.function,
            "line": message.line,
        }
        record = (json.dumps(event, ensure_ascii=False) + "\n").encode("utf-8")
        handler = self._errors if message.level >= Log.ERROR else self._application
        sizing_record = logging.LogRecord("rosout", logging.INFO, "", 0, record.decode("utf-8"), (), None)
        if handler.shouldRollover(sizing_record):
            handler.doRollover()
        handler.stream.write(record.decode("utf-8"))
        handler.flush()
        output = String()
        output.data = record.decode("utf-8").strip()
        self._publisher.publish(output)

    def destroy_node(self) -> None:
        self._application.close()
        self._errors.close()
        super().destroy_node()


def main(args=None) -> None:
    rclpy.init(args=args)
    node = LogCollector()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()
