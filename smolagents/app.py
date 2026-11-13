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
    # share=False is load-bearing: smolagents' GradioUI.launch defaults to
    # share=True, which opens a public *.gradio.live tunnel to an agent that
    # can dispatch jobs and run write tools. LAN access goes via name-proxy.
    GradioUI(build_manager_agent(), file_upload_folder=str(upload_dir)).launch(
        server_name="0.0.0.0", server_port=7860, share=False
    )


if __name__ == "__main__":
    main()
