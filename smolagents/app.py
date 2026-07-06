"""Gradio chat UI for the manager agent."""

from pathlib import Path

from smolagents import GradioUI

from agents import build_manager_agent, setup_telemetry, start_job_worker
from agents import config


def main() -> None:
    setup_telemetry()
    start_job_worker()  # background jobs dispatched via mcp-tools
    upload_dir = Path(config.DATA_DIR) / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    GradioUI(build_manager_agent(), file_upload_folder=str(upload_dir)).launch(
        server_name="0.0.0.0", server_port=7860
    )


if __name__ == "__main__":
    main()
