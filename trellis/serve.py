"""Thin FastAPI job server around the TRELLIS image-to-3D pipeline.

Async submit/poll: POST /generate queues a job, a single worker thread owns
the GPU (hard single-flight), results persist under /data/jobs/<id>/.
The pipeline lazy-loads on the first job and is unloaded again after
TRELLIS_IDLE_UNLOAD_S seconds without work — the 16 GB card is shared with
Ollama and ComfyUI, so VRAM is only held around generations.
"""

import json
import logging
import os
import queue
import threading
import time
import uuid
from pathlib import Path

import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("trellis")

MODEL_ID = os.environ.get("TRELLIS_MODEL_ID", "microsoft/TRELLIS-image-large")
DATA_DIR = Path(os.environ.get("TRELLIS_DATA_DIR", "/data"))
JOBS_DIR = DATA_DIR / "jobs"
IDLE_UNLOAD_S = int(os.environ.get("TRELLIS_IDLE_UNLOAD_S", "600"))

_weights_ready = False
_pipeline = None
_pipeline_lock = threading.Lock()
_last_used = time.monotonic()
_jobs: "queue.Queue[str]" = queue.Queue()

app = FastAPI(title="trellis", docs_url=None, redoc_url=None)


def _job_dir(job_id: str) -> Path:
    return JOBS_DIR / job_id


def _write_status(job_id: str, **fields) -> None:
    path = _job_dir(job_id) / "status.json"
    status = json.loads(path.read_text()) if path.exists() else {}
    status.update(fields, job_id=job_id, updated=time.strftime("%Y-%m-%dT%H:%M:%S"))
    path.write_text(json.dumps(status, indent=1))


def _download_weights() -> None:
    """Pre-fetch model weights to disk (no VRAM touched) so /healthz can
    report readiness and the first job doesn't stall on a 4.5 GB download."""
    global _weights_ready
    from huggingface_hub import snapshot_download
    try:
        snapshot_download(MODEL_ID)
        _weights_ready = True
        log.info("model weights ready: %s", MODEL_ID)
    except Exception:
        log.exception("weight download failed — will retry on first job")


def _load_pipeline():
    global _pipeline
    if _pipeline is None:
        log.info("loading pipeline %s onto GPU...", MODEL_ID)
        from trellis.pipelines import TrellisImageTo3DPipeline
        _pipeline = TrellisImageTo3DPipeline.from_pretrained(MODEL_ID)
        _pipeline.cuda()
        log.info("pipeline loaded")
    return _pipeline


def _unload_pipeline() -> None:
    global _pipeline
    if _pipeline is not None:
        log.info("idle %ss — unloading pipeline to free VRAM", IDLE_UNLOAD_S)
        import torch
        _pipeline = None
        torch.cuda.empty_cache()


def _run_job(job_id: str) -> None:
    from PIL import Image
    from trellis.utils import postprocessing_utils

    job_dir = _job_dir(job_id)
    params = json.loads((job_dir / "params.json").read_text())
    image = Image.open(job_dir / "input.png")

    pipeline = _load_pipeline()
    seed = params["seed"]
    outputs = pipeline.run(
        image,
        seed=seed,
        formats=["gaussian", "mesh"],
        sparse_structure_sampler_params={
            "steps": params["ss_steps"], "cfg_strength": params["ss_cfg"]},
        slat_sampler_params={
            "steps": params["slat_steps"], "cfg_strength": params["slat_cfg"]},
    )
    glb = postprocessing_utils.to_glb(
        outputs["gaussian"][0], outputs["mesh"][0],
        simplify=params["simplify"], texture_size=params["texture_size"])
    glb.export(job_dir / "model.glb")


def _worker() -> None:
    global _last_used
    while True:
        try:
            job_id = _jobs.get(timeout=5)
        except queue.Empty:
            with _pipeline_lock:
                if _jobs.empty() and IDLE_UNLOAD_S > 0 \
                        and time.monotonic() - _last_used > IDLE_UNLOAD_S:
                    _unload_pipeline()
            continue
        _write_status(job_id, status="running")
        started = time.monotonic()
        try:
            with _pipeline_lock:
                _run_job(job_id)
                _last_used = time.monotonic()
            _write_status(job_id, status="completed",
                          seconds=round(time.monotonic() - started, 1))
            log.info("job %s completed in %.0fs", job_id, time.monotonic() - started)
        except Exception as exc:
            log.exception("job %s failed", job_id)
            _write_status(job_id, status="failed", error=f"{type(exc).__name__}: {exc}")


@app.get("/healthz")
def healthz():
    return {"status": "ok", "model": MODEL_ID, "weights_ready": _weights_ready,
            "model_loaded": _pipeline is not None, "queue_depth": _jobs.qsize()}


@app.post("/generate")
async def generate(image: UploadFile = File(...),
                   seed: int = Form(-1),
                   texture_size: int = Form(1024),
                   simplify: float = Form(0.95),
                   ss_steps: int = Form(12),
                   ss_cfg: float = Form(7.5),
                   slat_steps: int = Form(12),
                   slat_cfg: float = Form(3.0)):
    if texture_size not in (512, 1024, 2048):
        raise HTTPException(422, "texture_size must be 512, 1024 or 2048")
    if not 0 <= simplify <= 0.98:
        raise HTTPException(422, "simplify must be between 0 and 0.98")
    if seed < 0:
        seed = int.from_bytes(os.urandom(4), "big")

    from PIL import Image, UnidentifiedImageError
    job_id = uuid.uuid4().hex[:12]
    job_dir = _job_dir(job_id)
    job_dir.mkdir(parents=True)
    try:
        Image.open(image.file).convert("RGBA").save(job_dir / "input.png")
    except UnidentifiedImageError:
        job_dir.rmdir()
        raise HTTPException(422, "upload is not a decodable image")

    (job_dir / "params.json").write_text(json.dumps(
        {"seed": seed, "texture_size": texture_size, "simplify": simplify,
         "ss_steps": ss_steps, "ss_cfg": ss_cfg,
         "slat_steps": slat_steps, "slat_cfg": slat_cfg}))
    _write_status(job_id, status="queued", seed=seed)
    _jobs.put(job_id)
    return {"job_id": job_id, "seed": seed}


@app.get("/jobs/{job_id}")
def job_status(job_id: str):
    path = _job_dir(job_id) / "status.json"
    if not path.exists():
        raise HTTPException(404, "unknown job id")
    return JSONResponse(json.loads(path.read_text()))


@app.get("/jobs/{job_id}/model.glb")
def job_model(job_id: str):
    path = _job_dir(job_id) / "model.glb"
    if not path.exists():
        raise HTTPException(404, "no model for this job (not finished, failed, or unknown)")
    return FileResponse(path, media_type="model/gltf-binary",
                        filename=f"trellis-{job_id}.glb")


if __name__ == "__main__":
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    threading.Thread(target=_download_weights, daemon=True).start()
    threading.Thread(target=_worker, daemon=True).start()
    uvicorn.run(app, host="0.0.0.0", port=8000)
