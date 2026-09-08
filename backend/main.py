import os
import json
import time
import requests
from pathlib import Path
from typing import Optional
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="MiniMax H3 Cloud Studio")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_FILE = BASE_DIR / "config.json"
OUTPUT_DIR = BASE_DIR / "outputs"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
STATIC_DIR = BASE_DIR / "static"
STATIC_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

DEFAULT_CONFIG = {
    "pod_id": "v0wf6t6p0d29l6",
    "comfyui_url": "https://v0wf6t6p0d29l6-8188.proxy.runpod.net",
    "runpod_api_key": "",
    "gpu_cost_per_hour": 0.74
}

def load_config():
    cfg = DEFAULT_CONFIG.copy()
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg.update(json.load(f))
        except Exception:
            pass
    # Override with Environment Variables (especially for Render Cloud deployment)
    if os.environ.get("RUNPOD_API_KEY"):
        cfg["runpod_api_key"] = os.environ.get("RUNPOD_API_KEY")
    if os.environ.get("RUNPOD_POD_ID"):
        cfg["pod_id"] = os.environ.get("RUNPOD_POD_ID")
    if os.environ.get("COMFYUI_URL"):
        cfg["comfyui_url"] = os.environ.get("COMFYUI_URL")
    return cfg

def save_config(cfg):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

@app.get("/api/config")
def get_config_endpoint():
    cfg = load_config()
    masked_key = cfg.get("runpod_api_key", "")
    if len(masked_key) > 8:
        masked_key = masked_key[:4] + "..." + masked_key[-4:]
    return {
        "pod_id": cfg.get("pod_id", ""),
        "comfyui_url": cfg.get("comfyui_url", ""),
        "gpu_cost_per_hour": cfg.get("gpu_cost_per_hour", 0.74),
        "has_api_key": bool(cfg.get("runpod_api_key")),
        "masked_api_key": masked_key
    }

class ConfigUpdateRequest(BaseModel):
    pod_id: Optional[str] = None
    comfyui_url: Optional[str] = None
    runpod_api_key: Optional[str] = None
    gpu_cost_per_hour: Optional[float] = None

@app.post("/api/config")
def update_config_endpoint(req: ConfigUpdateRequest):
    cfg = load_config()
    if req.pod_id is not None:
        cfg["pod_id"] = req.pod_id.strip()
        if not req.comfyui_url:
            cfg["comfyui_url"] = f"https://{cfg['pod_id']}-8188.proxy.runpod.net"
    if req.comfyui_url is not None:
        cfg["comfyui_url"] = req.comfyui_url.strip().rstrip("/")
    if req.runpod_api_key is not None and req.runpod_api_key != "":
        cfg["runpod_api_key"] = req.runpod_api_key.strip()
    if req.gpu_cost_per_hour is not None:
        cfg["gpu_cost_per_hour"] = req.gpu_cost_per_hour
    save_config(cfg)
    return {"status": "success", "message": "บันทึกการตั้งค่าเรียบร้อย"}

@app.get("/api/system/status")
def check_system_status():
    cfg = load_config()
    comfy_url = cfg.get("comfyui_url", "").rstrip("/")
    pod_id = cfg.get("pod_id", "")
    api_key = cfg.get("runpod_api_key", "")
    
    result = {
        "comfyui_online": False,
        "gpu_name": "NVIDIA RTX 4090",
        "vram_total_gb": 24.0,
        "vram_free_gb": 0,
        "vram_used_gb": 0,
        "ram_total_gb": 0,
        "ram_free_gb": 0,
        "ram_used_gb": 0,
        "cpu_info": "12 vCPUs",
        "queue_running": 0,
        "queue_pending": 0,
        "balance_usd": None,
        "pod_status": "UNKNOWN",
        "pod_id": pod_id
    }
    
    if comfy_url:
        try:
            r = requests.get(f"{comfy_url}/system_stats", headers=HEADERS, timeout=4)
            if r.status_code == 200:
                stats = r.json()
                result["comfyui_online"] = True
                
                # System RAM
                sys_info = stats.get("system", {})
                ram_total = sys_info.get("ram_total", 0)
                ram_free = sys_info.get("ram_free", 0)
                if ram_total > 0:
                    result["ram_total_gb"] = round(ram_total / (1024**3), 1)
                    result["ram_free_gb"] = round(ram_free / (1024**3), 1)
                    result["ram_used_gb"] = round((ram_total - ram_free) / (1024**3), 1)

                # GPU VRAM
                devices = stats.get("devices", [])
                if devices:
                    d = devices[0]
                    clean_name = d.get("name", "NVIDIA RTX 4090").split(":")[1].split("(")[0].strip() if ":" in d.get("name", "") else d.get("name", "NVIDIA RTX 4090")
                    result["gpu_name"] = clean_name
                    v_total = d.get("vram_total", 0) / (1024**3)
                    v_free = d.get("vram_free", 0) / (1024**3)
                    result["vram_total_gb"] = round(v_total, 1)
                    result["vram_free_gb"] = round(v_free, 1)
                    result["vram_used_gb"] = round(v_total - v_free, 1)
        except Exception:
            pass
            
        if result["comfyui_online"]:
            try:
                rq = requests.get(f"{comfy_url}/queue", headers=HEADERS, timeout=4)
                if rq.status_code == 200:
                    q_data = rq.json()
                    result["queue_running"] = len(q_data.get("queue_running", []))
                    result["queue_pending"] = len(q_data.get("queue_pending", []))
            except Exception:
                pass

    if api_key:
        try:
            graphql_url = f"https://api.runpod.io/graphql?api_key={api_key}"
            query = """
            query {
                myself {
                    id
                    email
                    pods {
                        id
                        name
                        desiredStatus
                        costPerHr
                    }
                }
            }
            """
            resp = requests.post(graphql_url, json={"query": query}, timeout=5)
            if resp.status_code == 200:
                data = resp.json().get("data", {})
                myself = data.get("myself")
                if myself:
                    result["user_email"] = myself.get("email")
                    result["api_connected"] = True
                    pods = myself.get("pods", [])
                    result["user_pods"] = pods
                    active_running = [p for p in pods if p.get("desiredStatus") == "RUNNING"]
                    if active_running:
                        current_active_id = active_running[0]["id"]
                        result["active_pod_id"] = current_active_id
                        result["cost_per_hr"] = active_running[0].get("costPerHr", 0.74)
                        result["pod_status"] = "RUNNING"
                        # Auto-update config if active pod id changed
                        if current_active_id != pod_id:
                            cfg["pod_id"] = current_active_id
                            cfg["comfyui_url"] = f"https://{current_active_id}-8188.proxy.runpod.net"
                            save_config(cfg)
                            result["pod_id"] = current_active_id
                    else:
                        result["pod_status"] = "STOPPED"
        except Exception:
            pass
            
    return result

@app.post("/api/pod/stop")
def stop_runpod_instance():
    cfg = load_config()
    api_key = cfg.get("runpod_api_key", "")
    pod_id = cfg.get("pod_id", "")
    
    if not api_key:
        raise HTTPException(status_code=400, detail="กรุณากรอก RunPod API Key ในแท็บตั้งค่าเพื่อใช้งานปุ่มหยุดเซิร์ฟเวอร์")
    if not pod_id:
        raise HTTPException(status_code=400, detail="ไม่พบ Pod ID")

    graphql_url = f"https://api.runpod.io/graphql?api_key={api_key}"
    mutation = """
    mutation {
        podStop(input: {podId: "%s"}) {
            id
            desiredStatus
        }
    }
    """ % pod_id
    try:
        resp = requests.post(graphql_url, json={"query": mutation}, timeout=8)
        data = resp.json()
        if "errors" in data:
            raise HTTPException(status_code=500, detail=str(data["errors"]))
        return {"status": "success", "message": f"สั่งหยุด Pod {pod_id} สำเร็จแล้ว (หยุดคิดค่า GPU ทันที)"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"เกิดข้อผิดพลาด: {str(e)}")

@app.get("/api/workflow/download")
def download_workflow():
    wf_path = BASE_DIR / "minimax_h3_clean_pro_workflow.json"
    if not wf_path.exists():
        raise HTTPException(status_code=404, detail="Workflow not found")
    return FileResponse(str(wf_path), media_type="application/json", filename="minimax_h3_clean_pro_workflow.json")

@app.post("/api/pod/start")
def start_runpod_instance():
    cfg = load_config()
    api_key = cfg.get("runpod_api_key", "")
    pod_id = cfg.get("pod_id", "")
    
    if not api_key:
        raise HTTPException(status_code=400, detail="กรุณากรอก RunPod API Key ในแท็บตั้งค่า")
    if not pod_id:
        raise HTTPException(status_code=400, detail="ไม่พบ Pod ID")

    graphql_url = f"https://api.runpod.io/graphql?api_key={api_key}"
    mutation = """
    mutation {
        podResume(input: {podId: "%s", gpuCount: 1}) {
            id
            desiredStatus
        }
    }
    """ % pod_id
    try:
        resp = requests.post(graphql_url, json={"query": mutation}, timeout=8)
        data = resp.json()
        if "errors" in data:
            raise HTTPException(status_code=500, detail=str(data["errors"]))
        return {"status": "success", "message": f"สั่งเริ่ม Pod {pod_id} สำเร็จ กำลังเปิดเครื่อง..."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"เกิดข้อผิดพลาด: {str(e)}")

class TTSRequest(BaseModel):
    text: str
    voice: str = "th-TH-NiwatNeural"
    rate: str = "+10%"

@app.post("/api/tts/generate")
async def generate_tts(req: TTSRequest):
    if not req.text.strip():
        raise HTTPException(status_code=400, detail="กรุณากรอกข้อความที่ต้องการสร้างเสียง")
    try:
        import edge_tts
        out_filename = f"tts_voice_{int(time.time())}.mp3"
        out_path = os.path.join(STATIC_DIR, out_filename)
        communicate = edge_tts.Communicate(req.text, req.voice, rate=req.rate)
        await communicate.save(out_path)
        return {
            "status": "success",
            "filename": out_filename,
            "url": f"/static/{out_filename}",
            "text": req.text
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"สร้างเสียงไม่สำเร็จ: {str(e)}")

def upload_file_to_comfy(comfy_url: str, file_bytes: bytes, filename: str):
    endpoint = f"{comfy_url}/upload/image"
    files = {"image": (filename, file_bytes)}
    data = {"subfolder": "", "type": "input", "overwrite": "true"}
    resp = requests.post(endpoint, files=files, data=data, headers=HEADERS, timeout=30)
    if resp.status_code == 200:
        return resp.json().get("name", filename)
    else:
        raise Exception(f"Upload failed: {resp.text}")

@app.post("/api/generate")
async def generate_video(
    face_image: UploadFile = File(...),
    voice_audio: UploadFile = File(...),
    prompt_text: str = Form(...),
    screen_image: Optional[UploadFile] = File(None),
    width: int = Form(1344),
    height: int = Form(768),
    length: int = Form(124),
    steps: int = Form(20),
    cfg_scale: float = Form(6.0),
    seed: Optional[int] = Form(None),
    auto_stop_pod: bool = Form(False)
):
    cfg = load_config()
    comfy_url = cfg.get("comfyui_url", "").rstrip("/")
    if not comfy_url:
        raise HTTPException(status_code=400, detail="ComfyUI URL ไม่ถูกต้อง")

    face_bytes = await face_image.read()
    audio_bytes = await voice_audio.read()
    screen_bytes = await screen_image.read() if screen_image else None

    try:
        uploaded_face = upload_file_to_comfy(comfy_url, face_bytes, face_image.filename)
        uploaded_audio = upload_file_to_comfy(comfy_url, audio_bytes, voice_audio.filename)
        uploaded_screen = upload_file_to_comfy(comfy_url, screen_bytes, screen_image.filename) if screen_bytes else None
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"อัปโหลดไฟล์ไปยัง ComfyUI ไม่สำเร็จ: {str(e)}")

    import random
    gen_seed = seed if (seed and seed > 0) else random.randint(100000000000000, 999999999999999)

    workflow_prompt = {
        "1": {
            "inputs": {
                "unet_name": "minimax_h3_ref2va_pruned_int8_convrot.safetensors",
                "weight_dtype": "default"
            },
            "class_type": "UNETLoader"
        },
        "2": {
            "inputs": {
                "clip_name": "qwen3vl_32b_minimax_h3_int8_convrot.safetensors",
                "type": "minimax",
                "device": "default"
            },
            "class_type": "CLIPLoader"
        },
        "3": {
            "inputs": {
                "vae_name": "minimax_h3_video_vae_fp16.safetensors"
            },
            "class_type": "VAELoader"
        },
        "4": {
            "inputs": {
                "vae_name": "minimax_h3_audio_vae_fp32.safetensors"
            },
            "class_type": "VAELoader"
        },
        "5": {
            "inputs": {
                "image": uploaded_face,
                "upload": "image"
            },
            "class_type": "LoadImage"
        },
        "7": {
            "inputs": {
                "audio": uploaded_audio
            },
            "class_type": "LoadAudio"
        },
        "8": {
            "inputs": {
                "prompt": prompt_text,
                "width": width,
                "height": height,
                "length": length,
                "ref_image_size": "match",
                "clip": ["2", 0],
                "vae": ["3", 0],
                "audio_vae": ["4", 0],
                "ref_images.ref_image_0": ["5", 0],
                "ref_audios.ref_audio_0": ["7", 0]
            },
            "class_type": "MiniMaxH3ReferenceToVideo"
        },
        "22": {
            "inputs": {
                "text": "",
                "clip": ["2", 0]
            },
            "class_type": "CLIPTextEncode"
        },
        "9": {
            "inputs": {
                "seed": gen_seed,
                "steps": steps,
                "cfg": cfg_scale,
                "sampler_name": "euler",
                "scheduler": "normal",
                "denoise": 1.0,
                "model": ["1", 0],
                "positive": ["8", 0],
                "negative": ["22", 0],
                "latent_image": ["8", 1]
            },
            "class_type": "KSampler"
        },
        "10": {
            "inputs": {
                "samples": ["9", 0],
                "vae": ["3", 0]
            },
            "class_type": "VAEDecode"
        },
        "21": {
            "inputs": {
                "images": ["10", 0],
                "fps": 24.0,
                "audio": ["7", 0]
            },
            "class_type": "CreateVideo"
        },
        "23": {
            "inputs": {
                "video": ["21", 0],
                "filename_prefix": "minimax_h3",
                "format": "mp4",
                "codec": "auto"
            },
            "class_type": "SaveVideo"
        }
    }

    if uploaded_screen:
        workflow_prompt["6"] = {
            "inputs": {
                "image": uploaded_screen,
                "upload": "image"
            },
            "class_type": "LoadImage"
        }
        workflow_prompt["8"]["inputs"]["ref_images.ref_image_1"] = ["6", 0]

    payload = {
        "prompt": workflow_prompt,
        "client_id": "minimax_h3_studio_client"
    }

    try:
        p_resp = requests.post(f"{comfy_url}/prompt", json=payload, headers=HEADERS, timeout=15)
        if p_resp.status_code != 200:
            raise Exception(f"ComfyUI Error: {p_resp.text}")
        prompt_data = p_resp.json()
        prompt_id = prompt_data.get("prompt_id")
        return {
            "status": "queued",
            "prompt_id": prompt_id,
            "seed": gen_seed,
            "auto_stop_pod": auto_stop_pod,
            "message": "ส่งงานเข้าคิวประมวลผล MiniMax H3 สำเร็จแล้ว"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"ไม่สามารถสั่งประมวลผลได้: {str(e)}")

@app.get("/api/job/status/{prompt_id}")
def check_job_status(prompt_id: str):
    cfg = load_config()
    comfy_url = cfg.get("comfyui_url", "").rstrip("/")
    
    try:
        h_resp = requests.get(f"{comfy_url}/history/{prompt_id}", headers=HEADERS, timeout=6)
        if h_resp.status_code == 200:
            data = h_resp.json()
            if prompt_id in data:
                job_info = data[prompt_id]
                status_obj = job_info.get("status", {})
                completed = status_obj.get("completed", False)
                status_str = status_obj.get("status_str", "")
                
                outputs = job_info.get("outputs", {})
                
                media_files = []
                for node_id, node_out in outputs.items():
                    if "images" in node_out:
                        for img in node_out["images"]:
                            fn = img.get("filename")
                            sf = img.get("subfolder", "")
                            tp = img.get("type", "output")
                            remote_url = f"{comfy_url}/view?filename={fn}&subfolder={sf}&type={tp}"
                            # Auto-download video to local outputs folder
                            if fn and fn.endswith(".mp4"):
                                local_path = OUTPUT_DIR / fn
                                if not local_path.exists():
                                    try:
                                        with requests.get(remote_url, headers=HEADERS, stream=True, timeout=15) as r:
                                            if r.status_code == 200:
                                                with open(local_path, "wb") as f_out:
                                                    for chunk in r.iter_content(chunk_size=8192):
                                                        f_out.write(chunk)
                                    except Exception:
                                        pass
                            media_files.append({
                                "filename": fn,
                                "subfolder": sf,
                                "type": tp,
                                "url": remote_url
                            })
                    if "gifs" in node_out or "videos" in node_out:
                        vlist = node_out.get("gifs", []) + node_out.get("videos", [])
                        for vid in vlist:
                            fn = vid.get("filename")
                            sf = vid.get("subfolder", "")
                            tp = vid.get("type", "output")
                            media_files.append({
                                "filename": fn,
                                "subfolder": sf,
                                "type": tp,
                                "url": f"{comfy_url}/view?filename={fn}&subfolder={sf}&type={tp}"
                            })
                            
                return {
                    "prompt_id": prompt_id,
                    "completed": completed,
                    "status": status_str,
                    "media": media_files,
                    "outputs": outputs
                }
    except Exception:
        pass
        
    return {
        "prompt_id": prompt_id,
        "completed": False,
        "status": "processing"
    }

from fastapi.responses import HTMLResponse

HTML_PAGE = """<!DOCTYPE html>
<html lang="th" class="dark">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>MiniMax H3 Cloud Studio | AI Video Creator</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
  <script>
    tailwind.config = {
      darkMode: 'class',
      theme: {
        extend: {
          colors: {
            brand: { 500: '#3b82f6', 600: '#2563eb' },
            surface: { 800: '#1e222d', 850: '#171a23', 900: '#0f1117', 950: '#0a0c10' }
          }
        }
      }
    }
  </script>
  <style>
    @import url('https://fonts.googleapis.com/css2?family=Prompt:wght@300;400;500;600&display=swap');
    body { font-family: 'Prompt', sans-serif; }
    .glass { background: rgba(30, 34, 45, 0.75); backdrop-filter: blur(12px); border: 1px solid rgba(255, 255, 255, 0.08); }
    .glass-danger { background: rgba(239, 68, 68, 0.12); border: 1px solid rgba(239, 68, 68, 0.35); }
  </style>
</head>
<body class="bg-surface-950 text-slate-100 min-h-screen flex flex-col">

  <!-- HEADER -->
  <header class="glass sticky top-0 z-50 border-b border-slate-800/80 px-4 lg:px-8 py-3 flex flex-wrap items-center justify-between gap-4">
    <div class="flex items-center gap-3">
      <div class="w-10 h-10 rounded-xl bg-gradient-to-tr from-blue-600 to-indigo-500 flex items-center justify-center shadow-lg shadow-blue-500/20">
        <i class="fa-solid fa-wand-magic-sparkles text-white text-lg"></i>
      </div>
      <div>
        <div class="flex items-center gap-2">
          <h1 class="font-bold text-lg tracking-tight text-white">MiniMax H3 Studio</h1>
          <span class="px-2 py-0.5 text-xs font-semibold rounded-full bg-blue-500/10 text-blue-400 border border-blue-500/20">Ref2VA Cloud</span>
        </div>
        <p class="text-xs text-slate-400">สร้างวิดีโอสมจริงพากย์ไทยด้วย RunPod RTX 4090</p>
      </div>
    </div>

    <div class="flex items-center flex-wrap gap-3">
      <div class="glass px-3 py-1.5 rounded-lg flex items-center gap-2 border border-slate-700/50">
        <i class="fa-solid fa-circle-check text-emerald-400 text-sm"></i>
        <div class="text-xs">
          <span class="text-slate-400">RunPod API:</span>
          <span id="balanceDisplay" class="font-semibold text-emerald-400 ml-1">กำลังตรวจ...</span>
        </div>
      </div>

      <div class="glass px-3 py-1.5 rounded-lg flex items-center gap-2 border border-slate-700/50">
        <span id="statusDot" class="w-2.5 h-2.5 rounded-full bg-yellow-400 animate-pulse"></span>
        <span id="statusText" class="text-xs font-medium text-slate-300">กำลังตรวจสถานะ...</span>
      </div>

      <!-- CPU, RAM, VRAM Badges -->
      <div id="hwHeaderStats" class="hidden flex items-center gap-2">
        <div class="glass px-2.5 py-1 rounded-lg flex items-center gap-1.5 border border-slate-700/50 text-[11px]">
          <i class="fa-solid fa-microchip text-blue-400"></i>
          <span class="text-slate-400">CPU:</span>
          <span id="headerCpu" class="font-semibold text-slate-200">12 vCPUs</span>
        </div>
        <div class="glass px-2.5 py-1 rounded-lg flex items-center gap-1.5 border border-slate-700/50 text-[11px]">
          <i class="fa-solid fa-memory text-purple-400"></i>
          <span class="text-slate-400">RAM:</span>
          <span id="headerRam" class="font-semibold text-purple-300">-- / -- GB</span>
        </div>
        <div class="glass px-2.5 py-1 rounded-lg flex items-center gap-1.5 border border-slate-700/50 text-[11px]">
          <i class="fa-solid fa-bolt text-emerald-400"></i>
          <span class="text-slate-400">VRAM:</span>
          <span id="headerVram" class="font-semibold text-emerald-400">-- / -- GB</span>
        </div>
      </div>

      <!-- Server Control Buttons -->
      <a href="/api/workflow/download" download class="glass hover:bg-slate-800 text-blue-400 hover:text-blue-300 border border-blue-500/40 px-3 py-1.5 rounded-lg text-xs font-semibold flex items-center gap-1.5 transition-all">
        <i class="fa-solid fa-download"></i>
        <span>โหลด Workflow ComfyUI</span>
      </a>

      <button id="btnStartServer" onclick="startServerAction()" class="hidden bg-emerald-600/30 hover:bg-emerald-600/50 text-emerald-400 hover:text-emerald-300 border border-emerald-500/40 px-3.5 py-1.5 rounded-lg text-xs font-semibold flex items-center gap-2 transition-all">
        <i class="fa-solid fa-play text-sm"></i>
        <span>เปิดเครื่อง (Start GPU)</span>
      </button>

      <button id="btnStopServer" onclick="confirmStopServer()" class="glass-danger hover:bg-red-600/30 text-red-400 hover:text-red-300 px-3.5 py-1.5 rounded-lg text-xs font-semibold flex items-center gap-2 transition-all">
        <i class="fa-solid fa-power-off text-sm"></i>
        <span>หยุดเซิร์ฟเวอร์ (ตัดค่าไฟ)</span>
      </button>

      <button onclick="openConfigModal()" class="glass hover:bg-slate-800 text-slate-300 px-3 py-1.5 rounded-lg text-xs font-medium border border-slate-700/60 transition-all flex items-center gap-1.5">
        <i class="fa-solid fa-sliders"></i>
        <span>ตั้งค่า API</span>
      </button>
    </div>
  </header>

  <!-- MAIN -->
  <main class="flex-1 max-w-7xl w-full mx-auto px-4 lg:px-8 py-6 grid grid-cols-1 lg:grid-cols-12 gap-6">
    <!-- LEFT COLUMN -->
    <div class="lg:col-span-7 space-y-6">
      <div class="glass rounded-2xl p-5 border border-slate-800">
        <div class="flex items-center justify-between mb-4">
          <div class="flex items-center gap-2">
            <span class="w-6 h-6 rounded-full bg-blue-600/20 text-blue-400 text-xs font-bold flex items-center justify-center border border-blue-500/30">1</span>
            <h2 class="font-semibold text-slate-100 text-sm">ไฟล์อ้างอิงภาพและเสียง (Reference Assets)</h2>
          </div>
          <span class="text-xs text-slate-400">JPG, PNG, WAV, MP3</span>
        </div>

        <div class="grid grid-cols-1 md:grid-cols-3 gap-4">
          <div class="relative group">
            <label class="block text-xs font-medium text-slate-300 mb-1.5 flex items-center gap-1.5">
              <i class="fa-solid fa-user-tie text-blue-400"></i>
              <span>ภาพใบหน้า &lt;Picture 1&gt;</span>
            </label>
            <div id="dropFace" onclick="document.getElementById('fileFace').click()" class="border-2 border-dashed border-slate-700 hover:border-blue-500 rounded-xl p-3 text-center cursor-pointer bg-surface-900/50 hover:bg-surface-900 transition flex flex-col items-center justify-center min-h-[140px]">
              <input type="file" id="fileFace" accept="image/*" class="hidden" onchange="previewFile(this, 'previewFace', 'iconFace')">
              <img id="previewFace" class="hidden w-full h-28 object-cover rounded-lg mb-1" />
              <div id="iconFace" class="space-y-1">
                <i class="fa-regular fa-image text-2xl text-slate-500 group-hover:text-blue-400 transition"></i>
                <p class="text-[11px] text-slate-400">เลือกภาพหน้าคุณ</p>
              </div>
            </div>
          </div>

          <div class="relative group">
            <label class="block text-xs font-medium text-slate-300 mb-1.5 flex items-center justify-between">
              <div class="flex items-center gap-1.5">
                <i class="fa-solid fa-desktop text-purple-400"></i>
                <span>ภาพฉาก/จอ &lt;Picture 2&gt;</span>
              </div>
              <span class="text-[10px] text-slate-500">(ไม่ใส่ก็ได้ AI เสกฉากให้)</span>
            </label>
            <div id="dropScreen" onclick="document.getElementById('fileScreen').click()" class="border-2 border-dashed border-slate-700 hover:border-purple-500 rounded-xl p-3 text-center cursor-pointer bg-surface-900/50 hover:bg-surface-900 transition flex flex-col items-center justify-center min-h-[140px]">
              <input type="file" id="fileScreen" accept="image/*" class="hidden" onchange="previewFile(this, 'previewScreen', 'iconScreen')">
              <img id="previewScreen" class="hidden w-full h-28 object-cover rounded-lg mb-1" />
              <div id="iconScreen" class="space-y-1">
                <i class="fa-solid fa-wand-magic-sparkles text-2xl text-slate-500 group-hover:text-purple-400 transition"></i>
                <p class="text-[11px] text-slate-400">ไม่ใส่ = AI เจนฉากหลังตาม Prompt</p>
                <p class="text-[9px] text-slate-500">หรือคลิกเพื่อเลือกภาพฉากของคุณเอง</p>
              </div>
            </div>
          </div>

          <div class="relative group">
            <label class="block text-xs font-medium text-slate-300 mb-1.5 flex items-center gap-1.5">
              <i class="fa-solid fa-microphone-lines text-emerald-400"></i>
              <span>เสียงพากย์ &lt;Audio 1&gt;</span>
            </label>
            <div id="dropAudio" onclick="document.getElementById('fileAudio').click()" class="border-2 border-dashed border-slate-700 hover:border-emerald-500 rounded-xl p-3 text-center cursor-pointer bg-surface-900/50 hover:bg-surface-900 transition flex flex-col items-center justify-center min-h-[140px]">
              <input type="file" id="fileAudio" accept="audio/*" class="hidden" onchange="previewAudioFile(this)">
              <div id="audioInfoBox" class="hidden w-full text-left space-y-1">
                <p id="audioFileName" class="text-xs font-medium text-emerald-400 truncate"></p>
                <audio id="audioPreview" controls class="w-full h-8 mt-2 scale-90 -mx-2"></audio>
              </div>
              <div id="iconAudio" class="space-y-1">
                <i class="fa-solid fa-volume-high text-2xl text-slate-500 group-hover:text-emerald-400 transition"></i>
                <p class="text-[11px] text-slate-400">เลือกไฟล์เสียงพากย์ หรือกดเจนเสียง AI</p>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div class="glass rounded-2xl p-5 border border-slate-800 space-y-3">
        <div class="flex items-center justify-between">
          <div class="flex items-center gap-2">
            <span class="w-6 h-6 rounded-full bg-blue-600/20 text-blue-400 text-xs font-bold flex items-center justify-center border border-blue-500/30">2</span>
            <h2 class="font-semibold text-slate-100 text-sm">สคริปต์คำสั่งและการแสดง (Prompt & Action)</h2>
          </div>
          <div class="flex items-center gap-1.5">
            <button onclick="quickGenerateVoice()" id="btnQuickTTS" class="px-2.5 py-1 text-[11px] font-semibold rounded-md bg-emerald-600/30 hover:bg-emerald-600/50 text-emerald-300 border border-emerald-500/40 transition flex items-center gap-1.5">
              <i class="fa-solid fa-wand-magic-sparkles"></i>
              <span>กดเจนเสียงพูด AI อัตโนมัติ</span>
            </button>
            <button onclick="applyPreset('tech_creator')" class="px-2.5 py-1 text-[11px] rounded-md bg-slate-800 hover:bg-slate-700 text-slate-300 transition">ประโยคใหม่</button>
            <button onclick="applyPreset('tech_review')" class="px-2.5 py-1 text-[11px] rounded-md bg-slate-800 hover:bg-slate-700 text-slate-300 transition">รีวิวคอม</button>
          </div>
        </div>

        <div class="relative">
          <textarea id="promptInput" rows="4" class="w-full bg-surface-900 border border-slate-700 rounded-xl p-3.5 text-xs text-slate-200 placeholder-slate-500 focus:outline-none focus:border-blue-500 leading-relaxed resize-none font-mono">A video of &lt;Picture 1&gt; gesturing enthusiastically towards &lt;Picture 2&gt; beside him. Speaking smoothly with voice &lt;Audio 1&gt; in Thai: "สวัสดีครับเพื่อนๆ ทุกคน! วันนี้ผมพามาดูการสร้าง AI อวตารพูดไทย ที่ขยับปากได้เนียนและตรงตามเสียงพูดแบบนี้เลยครับ". 4k studio lighting, clear voice and crisp lip sync.</textarea>
          <div class="flex items-center justify-between mt-2 text-[11px] text-slate-400">
            <span>แท็ก: <code class="text-blue-400">&lt;Picture 1&gt;</code> (หน้า), <code class="text-purple-400">&lt;Picture 2&gt;</code> (จอ), <code class="text-emerald-400">&lt;Audio 1&gt;</code> (เสียง)</span>
            <span id="charCount">0 ตัวอักษร</span>
          </div>
        </div>
      </div>

      <details class="glass rounded-2xl p-4 border border-slate-800 text-xs">
        <summary class="font-medium text-slate-300 cursor-pointer flex items-center justify-between">
          <div class="flex items-center gap-2">
            <i class="fa-solid fa-gear text-slate-400"></i>
            <span>การตั้งค่าขั้นสูง (ความละเอียด, เฟรม, Steps)</span>
          </div>
          <i class="fa-solid fa-chevron-down text-slate-500"></i>
        </summary>
        <div class="grid grid-cols-2 md:grid-cols-4 gap-4 mt-4 pt-3 border-t border-slate-800">
          <div>
            <label class="block text-slate-400 mb-1">ความละเอียด</label>
            <select id="settingRes" class="w-full bg-surface-900 border border-slate-700 rounded-lg p-2 text-xs text-slate-200">
              <option value="1344x768" selected>1344 x 768 (16:9 แนวนอน)</option>
              <option value="768x1344">768 x 1344 (9:16 มือถือ)</option>
              <option value="1024x1024">1024 x 1024 (1:1 จัตุรัส)</option>
            </select>
          </div>
          <div>
            <label class="block text-slate-400 mb-1">จำนวนเฟรม (ความยาว)</label>
            <input type="number" id="settingLength" value="124" class="w-full bg-surface-900 border border-slate-700 rounded-lg p-2 text-xs text-slate-200">
            <span class="text-[10px] text-slate-500">124 เฟรม = ~5 วินาที</span>
          </div>
          <div>
            <label class="block text-slate-400 mb-1">Sampling Steps</label>
            <input type="number" id="settingSteps" value="20" class="w-full bg-surface-900 border border-slate-700 rounded-lg p-2 text-xs text-slate-200">
          </div>
          <div>
            <label class="block text-slate-400 mb-1">CFG Scale</label>
            <input type="number" step="0.5" id="settingCfg" value="6.0" class="w-full bg-surface-900 border border-slate-700 rounded-lg p-2 text-xs text-slate-200">
          </div>
        </div>
      </details>

      <div class="space-y-3">
        <label class="flex items-center gap-2 cursor-pointer text-xs text-slate-300 bg-surface-900/60 p-3 rounded-xl border border-slate-800">
          <input type="checkbox" id="chkAutoStop" class="w-4 h-4 rounded text-blue-600 focus:ring-0 bg-surface-850 border-slate-700">
          <span><strong>Auto-Stop Cloud Server</strong>: หยุดเซิร์ฟเวอร์ RunPod อัตโนมัติทันทีหลังจากสร้างวิดีโอเสร็จ (ตัดเงินค่า GPU ทันที)</span>
        </label>

        <button id="btnGenerate" onclick="startGeneration()" class="w-full py-4 rounded-xl bg-gradient-to-r from-blue-600 via-indigo-600 to-purple-600 hover:from-blue-500 hover:to-purple-500 font-bold text-sm tracking-wide text-white shadow-xl shadow-blue-600/25 flex items-center justify-center gap-2 transition-all transform active:scale-[0.99]">
          <i class="fa-solid fa-play"></i>
          <span>เริ่มสร้างวิดีโอ (Generate MiniMax H3 Video)</span>
        </button>
      </div>
    </div>

    <!-- RIGHT COLUMN -->
    <div class="lg:col-span-5 space-y-6">
      <div class="glass rounded-2xl p-5 border border-slate-800 space-y-4">
        <div class="flex items-center justify-between">
          <h2 class="font-semibold text-slate-100 text-sm flex items-center gap-2">
            <i class="fa-solid fa-chart-line text-blue-400"></i>
            <span>สถานะการประมวลผล (Live Progress)</span>
          </h2>
          <span id="elapsedTimer" class="font-mono text-xs text-slate-400">00:00</span>
        </div>

        <div class="space-y-2">
          <div class="flex justify-between text-xs text-slate-400">
            <span id="taskStatusLabel">พร้อมเริ่มประมวลผล</span>
            <span id="taskPercentLabel">0%</span>
          </div>
          <div class="w-full bg-surface-900 h-2.5 rounded-full overflow-hidden border border-slate-800">
            <div id="progressBar" class="bg-gradient-to-r from-blue-500 to-indigo-500 h-full w-0 transition-all duration-300"></div>
          </div>
        </div>

        <div class="grid grid-cols-3 gap-2.5 pt-2 text-xs">
          <div class="bg-surface-900/90 p-3 rounded-xl border border-slate-800 space-y-1">
            <div class="flex items-center justify-between text-[11px] text-slate-400">
              <span class="flex items-center gap-1"><i class="fa-solid fa-microchip text-blue-400"></i> CPU</span>
              <span id="cardCpu" class="text-slate-300 font-medium">12 vCPUs</span>
            </div>
            <div class="text-xs font-semibold text-slate-200" id="cardCpuModel">AMD EPYC</div>
            <div class="w-full bg-slate-800 h-1.5 rounded-full overflow-hidden mt-1">
              <div class="bg-blue-500 h-full w-[25%]"></div>
            </div>
          </div>

          <div class="bg-surface-900/90 p-3 rounded-xl border border-slate-800 space-y-1">
            <div class="flex items-center justify-between text-[11px] text-slate-400">
              <span class="flex items-center gap-1"><i class="fa-solid fa-memory text-purple-400"></i> System RAM</span>
              <span id="cardRamPct" class="text-purple-300 font-medium">--%</span>
            </div>
            <div class="text-xs font-semibold text-slate-200" id="cardRamText">-- / 62 GB</div>
            <div class="w-full bg-slate-800 h-1.5 rounded-full overflow-hidden mt-1">
              <div id="barRam" class="bg-purple-500 h-full w-0 transition-all duration-300"></div>
            </div>
          </div>

          <div class="bg-surface-900/90 p-3 rounded-xl border border-slate-800 space-y-1">
            <div class="flex items-center justify-between text-[11px] text-slate-400">
              <span class="flex items-center gap-1"><i class="fa-solid fa-bolt text-emerald-400"></i> GPU VRAM</span>
              <span id="cardVramPct" class="text-emerald-400 font-medium">--%</span>
            </div>
            <div class="text-xs font-semibold text-slate-200" id="cardVramText">-- / 24 GB</div>
            <div class="w-full bg-slate-800 h-1.5 rounded-full overflow-hidden mt-1">
              <div id="barVram" class="bg-emerald-500 h-full w-0 transition-all duration-300"></div>
            </div>
          </div>
        </div>

        <div class="bg-surface-900/60 px-3 py-2 rounded-xl border border-slate-800 flex items-center justify-between text-xs">
          <span class="text-slate-400">ค่าใช้จ่ายโดยประมาณรอบนี้:</span>
          <span id="estCostDisplay" class="font-bold text-emerald-400">~$0.00</span>
        </div>
      </div>

      <div class="glass rounded-2xl p-5 border border-slate-800 space-y-4">
        <div class="flex items-center justify-between">
          <h2 class="font-semibold text-slate-100 text-sm flex items-center gap-2">
            <i class="fa-solid fa-film text-purple-400"></i>
            <span>ผลลัพธ์วิดีโอ (Output Player)</span>
          </h2>
          <a id="btnDownload" href="#" download="minimax_h3_video.mp4" class="hidden px-3 py-1 text-xs font-semibold rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white flex items-center gap-1.5 transition">
            <i class="fa-solid fa-download"></i>
            <span>ดาวน์โหลด .MP4</span>
          </a>
        </div>

        <div id="videoContainer" class="w-full aspect-video bg-surface-900 rounded-xl flex flex-col items-center justify-center border border-slate-800 overflow-hidden relative">
          <div id="videoPlaceholder" class="text-center p-6 space-y-2">
            <div class="w-12 h-12 rounded-full bg-surface-850 flex items-center justify-center mx-auto text-slate-600">
              <i class="fa-solid fa-video text-xl"></i>
            </div>
            <p class="text-xs text-slate-400">วิดีโอที่เรนเดอร์เสร็จจะปรากฏที่นี่</p>
            <p class="text-[11px] text-slate-500">ความยาว 5 วินาที พร้อมเสียงพากย์และขยับปากสมจริง</p>
          </div>
          <video id="resultVideo" controls class="hidden w-full h-full object-contain"></video>
        </div>
      </div>
    </div>
  </main>

  <!-- CONFIG MODAL -->
  <div id="configModal" class="hidden fixed inset-0 z-50 bg-black/70 backdrop-blur-sm flex items-center justify-center p-4">
    <div class="glass rounded-2xl max-w-md w-full p-6 border border-slate-700 space-y-4">
      <div class="flex items-center justify-between border-b border-slate-800 pb-3">
        <h3 class="font-bold text-slate-100 text-sm flex items-center gap-2">
          <i class="fa-solid fa-sliders text-blue-400"></i>
          <span>การตั้งค่าเชื่อมต่อ RunPod & ComfyUI</span>
        </h3>
        <button onclick="closeConfigModal()" class="text-slate-400 hover:text-white">
          <i class="fa-solid fa-xmark"></i>
        </button>
      </div>

      <div class="space-y-3 text-xs">
        <div>
          <label class="block text-slate-300 mb-1">RunPod API Key (สำหรับยืนยันบัญชีและสั่ง เปิด/ปิด GPU ตัดค่าไฟ)</label>
          <input type="password" id="cfgApiKey" placeholder="rpa_xxxxxxxxxxxxxxxx" class="w-full bg-surface-900 border border-slate-700 rounded-lg p-2.5 text-xs text-slate-200">
          <span class="text-[10px] text-slate-500">หาได้จาก RunPod Settings > API Keys</span>
        </div>

        <div>
          <label class="block text-slate-300 mb-1">RunPod Pod ID</label>
          <input type="text" id="cfgPodId" placeholder="v0wf6t6p0d29l6" class="w-full bg-surface-900 border border-slate-700 rounded-lg p-2.5 text-xs text-slate-200">
        </div>

        <div>
          <label class="block text-slate-300 mb-1">ComfyUI Endpoint URL</label>
          <input type="text" id="cfgComfyUrl" placeholder="https://v0wf6t6p0d29l6-8188.proxy.runpod.net" class="w-full bg-surface-900 border border-slate-700 rounded-lg p-2.5 text-xs text-slate-200">
        </div>
      </div>

      <div class="flex justify-end gap-2 pt-2">
        <button onclick="closeConfigModal()" class="px-4 py-2 rounded-lg bg-slate-800 text-slate-300 text-xs font-medium hover:bg-slate-700">ยกเลิก</button>
        <button onclick="saveConfig()" class="px-4 py-2 rounded-lg bg-blue-600 text-white text-xs font-medium hover:bg-blue-500">บันทึกการตั้งค่า</button>
      </div>
    </div>
  </div>

  <!-- STOP SERVER IN-UI MODAL -->
  <div id="stopConfirmModal" class="hidden fixed inset-0 z-50 bg-black/80 backdrop-blur-md flex items-center justify-center p-4">
    <div class="glass rounded-2xl max-w-md w-full p-6 border border-red-500/30 space-y-4 shadow-2xl shadow-red-950/40">
      <div class="flex items-center gap-3 border-b border-slate-800 pb-3">
        <div class="w-10 h-10 rounded-xl bg-red-600/20 text-red-400 flex items-center justify-center border border-red-500/30 text-lg">
          <i class="fa-solid fa-power-off"></i>
        </div>
        <div>
          <h3 class="font-bold text-slate-100 text-sm">ยืนยันการหยุดเซิร์ฟเวอร์ RunPod</h3>
          <p class="text-xs text-slate-400">ตัดค่าไฟ GPU ($0.74/ชม. $\rightarrow$ $0.00)</p>
        </div>
      </div>

      <div class="space-y-2 text-xs text-slate-300 bg-surface-900/80 p-3.5 rounded-xl border border-slate-800">
        <div class="flex items-start gap-2">
          <i class="fa-solid fa-check text-emerald-400 mt-0.5"></i>
          <span>ระบบจะสั่งหยุด Pod ทันที ไม่เสียเงินค่า GPU อีกต่อไป</span>
        </div>
        <div class="flex items-start gap-2">
          <i class="fa-solid fa-shield-halved text-blue-400 mt-0.5"></i>
          <span>ข้อมูลและโมเดล MiniMax H3 ยังคงบันทึกอยู่ใน Network Volume ปลอดภัย 100%</span>
        </div>
      </div>

      <div class="flex justify-end gap-2.5 pt-2">
        <button onclick="closeStopModal()" class="px-4 py-2 rounded-xl bg-slate-800 text-slate-300 text-xs font-medium hover:bg-slate-700 transition">ยกเลิก</button>
        <button id="btnConfirmStopReal" onclick="executeStopServer()" class="px-4 py-2 rounded-xl bg-red-600 hover:bg-red-500 text-white text-xs font-semibold shadow-lg shadow-red-600/30 flex items-center gap-2 transition">
          <i class="fa-solid fa-power-off"></i>
          <span>ยืนยันหยุดเซิร์ฟเวอร์</span>
        </button>
      </div>
    </div>
  </div>

  <!-- TOAST NOTIFICATION CONTAINER -->
  <div id="toastContainer" class="fixed bottom-6 right-6 z-50 space-y-2 pointer-events-none"></div>

  <script>
    let timerInterval = null;
    let elapsedSeconds = 0;
    let isGenerating = false;
    let pollInterval = null;

    document.addEventListener('DOMContentLoaded', () => {
      fetchConfig();
      fetchStatus();
      setInterval(fetchStatus, 8000);
      
      const promptInput = document.getElementById('promptInput');
      document.getElementById('charCount').innerText = `${promptInput.value.length} ตัวอักษร`;
      promptInput.addEventListener('input', (e) => {
        document.getElementById('charCount').innerText = `${e.target.value.length} ตัวอักษร`;
      });
    });

    async function fetchConfig() {
      try {
        const res = await fetch('/api/config');
        const data = await res.json();
        document.getElementById('cfgPodId').value = data.pod_id || '';
        document.getElementById('cfgComfyUrl').value = data.comfyui_url || '';
        if (data.masked_api_key) {
          document.getElementById('cfgApiKey').placeholder = `บันทึกไว้แล้ว (${data.masked_api_key})`;
        }
      } catch (err) {
        console.error('Failed to load config:', err);
      }
    }

    async function fetchStatus() {
      try {
        const res = await fetch('/api/system/status');
        const data = await res.json();

        const balanceEl = document.getElementById('balanceDisplay');
        if (data.api_connected && data.user_email) {
          const rate = data.cost_per_hr ? ` ($${data.cost_per_hr}/ชม.)` : '';
          balanceEl.innerHTML = `<span class="text-emerald-400">เชื่อมต่อแล้ว</span> <span class="text-slate-400 font-normal">(${data.user_email})${rate}</span>`;
        } else if (data.balance_usd !== null && data.balance_usd !== undefined) {
          balanceEl.innerText = `$${data.balance_usd.toFixed(2)} USD`;
        } else {
          balanceEl.innerHTML = '<span class="text-amber-400">ยังไม่ได้ใส่ API Key</span>';
        }

        const dot = document.getElementById('statusDot');
        const text = document.getElementById('statusText');
        const hwStats = document.getElementById('hwHeaderStats');
        const btnStart = document.getElementById('btnStartServer');
        const btnStop = document.getElementById('btnStopServer');

        if (data.comfyui_online) {
          dot.className = 'w-2.5 h-2.5 rounded-full bg-emerald-400 shadow-[0_0_8px_#34d399]';
          text.innerText = 'RunPod พร้อมรัน';
          text.className = 'text-xs font-semibold text-emerald-400';
          
          // Header Stats
          hwStats.classList.remove('hidden');
          document.getElementById('headerCpu').innerText = data.cpu_info || '12 vCPUs';
          document.getElementById('headerRam').innerText = `${data.ram_used_gb} / ${data.ram_total_gb} GB`;
          document.getElementById('headerVram').innerText = `${data.vram_used_gb} / ${data.vram_total_gb} GB`;

          // Right Column Cards
          document.getElementById('cardCpu').innerText = data.cpu_info || '12 vCPUs';
          
          const ramPct = data.ram_total_gb > 0 ? Math.round((data.ram_used_gb / data.ram_total_gb) * 100) : 0;
          document.getElementById('cardRamPct').innerText = `${ramPct}%`;
          document.getElementById('cardRamText').innerText = `${data.ram_used_gb} / ${data.ram_total_gb} GB`;
          document.getElementById('barRam').style.width = `${ramPct}%`;

          const vramPct = data.vram_total_gb > 0 ? Math.round((data.vram_used_gb / data.vram_total_gb) * 100) : 0;
          document.getElementById('cardVramPct').innerText = `${vramPct}%`;
          document.getElementById('cardVramText').innerText = `${data.vram_used_gb} / ${data.vram_total_gb} GB`;
          document.getElementById('barVram').style.width = `${vramPct}%`;

          btnStart.classList.add('hidden');
          btnStop.classList.remove('hidden');
        } else {
          dot.className = 'w-2.5 h-2.5 rounded-full bg-red-500';
          text.innerText = data.pod_status === 'RUNNING' ? 'เซิร์ฟเวอร์กำลังเปิดเครื่อง...' : 'เซิร์ฟเวอร์ออฟไลน์ / หยุดอยู่';
          text.className = 'text-xs font-semibold text-red-400';
          hwStats.classList.add('hidden');
          btnStart.classList.remove('hidden');
          btnStop.classList.add('hidden');
        }
      } catch (err) {
        console.error('Status fetch error:', err);
      }
    }

    function openConfigModal() {
      document.getElementById('configModal').classList.remove('hidden');
    }
    function closeConfigModal() {
      document.getElementById('configModal').classList.add('hidden');
    }

    async function saveConfig() {
      const pod_id = document.getElementById('cfgPodId').value.trim();
      const comfyui_url = document.getElementById('cfgComfyUrl').value.trim();
      const runpod_api_key = document.getElementById('cfgApiKey').value.trim();

      const payload = { pod_id, comfyui_url };
      if (runpod_api_key) payload.runpod_api_key = runpod_api_key;

      try {
        const res = await fetch('/api/config', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        });
        const data = await res.json();
        alert(data.message || 'บันทึกสำเร็จ');
        closeConfigModal();
        fetchStatus();
      } catch (e) {
        alert('เกิดข้อผิดพลาดในการบันทึก: ' + e);
      }
    }

    function showToast(message, type = 'info') {
      const container = document.getElementById('toastContainer');
      const toast = document.createElement('div');
      const bg = type === 'success' ? 'bg-emerald-950/90 border-emerald-500/50 text-emerald-300' :
                 type === 'danger' ? 'bg-red-950/90 border-red-500/50 text-red-300' :
                 'bg-slate-900/90 border-slate-700 text-slate-200';
      const icon = type === 'success' ? 'fa-circle-check text-emerald-400' :
                   type === 'danger' ? 'fa-triangle-exclamation text-red-400' :
                   'fa-circle-info text-blue-400';

      toast.className = `${bg} pointer-events-auto backdrop-blur-md px-4 py-3 rounded-xl border text-xs shadow-2xl flex items-center gap-3 transition-all duration-300 transform translate-y-4 opacity-0`;
      toast.innerHTML = `<i class="fa-solid ${icon} text-base"></i><span>${message}</span>`;
      container.appendChild(toast);

      setTimeout(() => {
        toast.classList.remove('translate-y-4', 'opacity-0');
      }, 10);

      setTimeout(() => {
        toast.classList.add('opacity-0', 'translate-y-2');
        setTimeout(() => toast.remove(), 300);
      }, 4000);
    }

    async function startServerAction() {
      const btn = document.getElementById('btnStartServer');
      btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> กำลังสั่งเปิดเครื่อง...';
      btn.disabled = true;

      try {
        const res = await fetch('/api/pod/start', { method: 'POST' });
        const data = await res.json();
        if (res.ok) {
          showToast(data.message || 'สั่งเปิดเครื่องสำเร็จ กำลังเตรียมระบบ...', 'success');
          fetchStatus();
        } else {
          showToast('ไม่สามารถเปิดเครื่องได้: ' + (data.detail || 'การ์ดจออาจไม่ว่าง'), 'danger');
        }
      } catch (e) {
        showToast('ข้อผิดพลาด: ' + e, 'danger');
      } finally {
        btn.innerHTML = '<i class="fa-solid fa-play text-sm"></i> <span>เปิดเครื่อง (Start GPU)</span>';
        btn.disabled = false;
      }
    }

    function confirmStopServer() {
      document.getElementById('stopConfirmModal').classList.remove('hidden');
    }

    function closeStopModal() {
      document.getElementById('stopConfirmModal').classList.add('hidden');
    }

    async function executeStopServer() {
      const btn = document.getElementById('btnConfirmStopReal');
      const orig = btn.innerHTML;
      btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> กำลังหยุด...';
      btn.disabled = true;

      try {
        const res = await fetch('/api/pod/stop', { method: 'POST' });
        const data = await res.json();
        closeStopModal();
        if (res.ok) {
          showToast(data.message, 'success');
          fetchStatus();
        } else {
          showToast('ไม่สามารถหยุดเซิร์ฟเวอร์ได้: ' + (data.detail || 'โปรดตรวจ API Key'), 'danger');
        }
      } catch (e) {
        showToast('ข้อผิดพลาด: ' + e, 'danger');
      } finally {
        btn.innerHTML = orig;
        btn.disabled = false;
      }
    }

    function previewFile(input, previewId, iconId) {
      if (input.files && input.files[0]) {
        const reader = new FileReader();
        reader.onload = (e) => {
          const img = document.getElementById(previewId);
          img.src = e.target.result;
          img.classList.remove('hidden');
          document.getElementById(iconId).classList.add('hidden');
        }
        reader.readAsDataURL(input.files[0]);
      }
    }

    function previewAudioFile(input) {
      if (input.files && input.files[0]) {
        const file = input.files[0];
        document.getElementById('audioFileName').innerText = file.name;
        const audio = document.getElementById('audioPreview');
        audio.src = URL.createObjectURL(file);
        document.getElementById('audioInfoBox').classList.remove('hidden');
        document.getElementById('iconAudio').classList.add('hidden');
      }
    }

    let generatedVoiceBlob = null;

    async function quickGenerateVoice() {
      const p = document.getElementById('promptInput').value;
      const match = p.match(/"([^"]+)"/);
      const textToSpeak = match ? match[1] : p;

      const btn = document.getElementById('btnQuickTTS');
      const originalText = btn.innerHTML;
      btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> กำลังเจนเสียง...';
      btn.disabled = true;

      try {
        const res = await fetch('/api/tts/generate', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ text: textToSpeak, voice: 'th-TH-NiwatNeural', rate: '+15%' })
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || 'ไม่สามารถเจนเสียงได้');

        // Fetch audio blob
        const audioRes = await fetch(data.url);
        generatedVoiceBlob = await audioRes.blob();
        
        // Populate into UI
        document.getElementById('audioFileName').innerText = `เสียง AI: "${textToSpeak.slice(0, 25)}..."`;
        const audio = document.getElementById('audioPreview');
        audio.src = data.url;
        document.getElementById('audioInfoBox').classList.remove('hidden');
        document.getElementById('iconAudio').classList.add('hidden');

        showToast(`เจนเสียงภาษาไทยสำเร็จ: "${textToSpeak.slice(0, 35)}..."`, 'success');
      } catch (err) {
        showToast('เกิดข้อผิดพลาดในการเจนเสียง: ' + err.message, 'danger');
      } finally {
        btn.innerHTML = originalText;
        btn.disabled = false;
      }
    }

    function applyPreset(type) {
      const p = document.getElementById('promptInput');
      if (type === 'tech_creator') {
        p.value = 'A video of <Picture 1> gesturing enthusiastically towards <Picture 2> beside him. Speaking smoothly with voice <Audio 1> in Thai: "สวัสดีครับเพื่อนๆ ทุกคน! วันนี้ผมพามาดูการสร้าง AI อวตารพูดไทย ที่ขยับปากได้เนียนและตรงตามเสียงพูดแบบนี้เลยครับ". 4k studio lighting, clear voice and crisp lip sync.';
      } else if (type === 'tech_review') {
        p.value = 'A video of <Picture 1> gesturing enthusiastically towards <Picture 2> beside him. He speaks with voice <Audio 1> in Thai: "ไม่ต้องพึ่งค่ายใหญ่แล้วครับ รันเองในเครื่องแบบนี้ ลื่นหัวแตกเลยครับ". High-end YouTube studio background, modern lighting, clear voice and crisp lip sync, 4k resolution.';
      }
      document.getElementById('charCount').innerText = `${p.value.length} ตัวอักษร`;
    }

    async function startGeneration() {
      const fileFace = document.getElementById('fileFace').files[0];
      const fileScreen = document.getElementById('fileScreen').files[0];
      let fileAudio = document.getElementById('fileAudio').files[0];
      const promptText = document.getElementById('promptInput').value.trim();

      if (!fileFace) return showToast('กรุณาเลือกภาพใบหน้าของคุณ <Picture 1>', 'danger');
      if (!promptText) return showToast('กรุณากรอกสคริปต์คำสั่ง', 'danger');

      // ถ้าผู้ใช้ไม่ได้อัปโหลดเสียง ให้สั่งเจนเสียงพูดไทยอัตโนมัติจาก Prompt ทันที
      let audioBlobToSend = fileAudio || generatedVoiceBlob;
      if (!audioBlobToSend) {
        showToast('กำลังเจนเสียงพากย์ไทยอัตโนมัติจากข้อความใน Prompt...', 'info');
        const match = promptText.match(/"([^"]+)"/);
        const textToSpeak = match ? match[1] : promptText;
        try {
          const ttsRes = await fetch('/api/tts/generate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ text: textToSpeak, voice: 'th-TH-NiwatNeural', rate: '+15%' })
          });
          const ttsData = await ttsRes.json();
          if (!ttsRes.ok) throw new Error(ttsData.detail || 'เจนเสียงไม่สำเร็จ');
          const aRes = await fetch(ttsData.url);
          audioBlobToSend = await aRes.blob();
          document.getElementById('audioFileName').innerText = `เสียง AI อัตโนมัติ: "${textToSpeak.slice(0, 20)}..."`;
          document.getElementById('audioPreview').src = ttsData.url;
          document.getElementById('audioInfoBox').classList.remove('hidden');
          document.getElementById('iconAudio').classList.add('hidden');
        } catch (e) {
          return showToast('สร้างเสียงพากย์อัตโนมัติไม่สำเร็จ: ' + e.message, 'danger');
        }
      }

      const formData = new FormData();
      formData.append('face_image', fileFace);
      if (fileScreen) {
        formData.append('screen_image', fileScreen);
      }
      if (fileAudio) {
        formData.append('voice_audio', fileAudio);
      } else {
        formData.append('voice_audio', audioBlobToSend, 'auto_generated_voice.mp3');
      }
      formData.append('prompt_text', promptText);

      const resVal = document.getElementById('settingRes').value.split('x');
      formData.append('width', resVal[0]);
      formData.append('height', resVal[1]);
      formData.append('length', document.getElementById('settingLength').value);
      formData.append('steps', document.getElementById('settingSteps').value);
      formData.append('cfg_scale', document.getElementById('settingCfg').value);
      formData.append('auto_stop_pod', document.getElementById('chkAutoStop').checked);

      const btnGen = document.getElementById('btnGenerate');
      btnGen.disabled = true;
      btnGen.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> กำลังส่งงานและอัปโหลดไฟล์...';
      
      document.getElementById('taskStatusLabel').innerText = 'กำลังส่งงานไปยัง ComfyUI Cloud...';
      document.getElementById('progressBar').style.width = '15%';
      document.getElementById('taskPercentLabel').innerText = '15%';

      elapsedSeconds = 0;
      clearInterval(timerInterval);
      timerInterval = setInterval(() => {
        elapsedSeconds++;
        const mins = String(Math.floor(elapsedSeconds / 60)).padStart(2, '0');
        const secs = String(elapsedSeconds % 60).padStart(2, '0');
        document.getElementById('elapsedTimer').innerText = `${mins}:${secs}`;
        
        const cost = (elapsedSeconds * (0.74 / 3600)).toFixed(3);
        document.getElementById('estCostDisplay').innerText = `~$${cost} USD`;
      }, 1000);

      try {
        const res = await fetch('/api/generate', {
          method: 'POST',
          body: formData
        });
        const data = await res.json();
        if (!res.ok) {
          throw new Error(data.detail || 'การสร้างล้มเหลว');
        }

        const promptId = data.prompt_id;
        document.getElementById('taskStatusLabel').innerText = 'AI กำลังเรนเดอร์โมเดล MiniMax H3 (KSampler)...';
        document.getElementById('progressBar').style.width = '35%';
        document.getElementById('taskPercentLabel').innerText = '35%';

        pollJob(promptId, data.auto_stop_pod);

      } catch (err) {
        alert('เกิดข้อผิดพลาด: ' + err.message);
        resetGenUI();
      }
    }

    function pollJob(promptId, autoStopPod) {
      if (pollInterval) clearInterval(pollInterval);

      // Connect to ComfyUI WebSocket for 100% accurate Live Step & Percentage
      try {
        const comfyUrlInput = document.getElementById('cfgComfyUrl').value.trim();
        const wsProto = comfyUrlInput.startsWith('https') ? 'wss:' : 'ws:';
        const host = comfyUrlInput.replace(/^https?:\/\//, '');
        const wsUrl = `${wsProto}//${host}/ws?clientId=minimax_h3_studio_client`;
        const ws = new WebSocket(wsUrl);

        ws.onmessage = (event) => {
          try {
            const msg = JSON.parse(event.data);
            if (msg.type === 'progress') {
              const val = msg.data.value;
              const max = msg.data.max;
              const pct = Math.round((val / max) * 100);
              document.getElementById('progressBar').style.width = `${pct}%`;
              document.getElementById('taskPercentLabel').innerText = `${pct}% (Step ${val}/${max})`;
              document.getElementById('taskStatusLabel').innerText = `กำลังคำนวณโมเดล MiniMax H3: Step ${val}/${max}...`;
            } else if (msg.type === 'executing') {
              const node = msg.data.node;
              if (node === '10') {
                document.getElementById('taskStatusLabel').innerText = 'กำลังถอดรหัสภาพวิดีโอ (VAEDecode)...';
                document.getElementById('progressBar').style.width = '88%';
                document.getElementById('taskPercentLabel').innerText = '88%';
              } else if (node === '24') {
                document.getElementById('taskStatusLabel').innerText = 'กำลังถอดรหัสเสียงพากย์ซิงค์ปาก (VAEDecodeAudio)...';
                document.getElementById('progressBar').style.width = '94%';
                document.getElementById('taskPercentLabel').innerText = '94%';
              } else if (node === '23') {
                document.getElementById('taskStatusLabel').innerText = 'กำลังบันทึกและแปลงเป็นไฟล์ .MP4...';
                document.getElementById('progressBar').style.width = '98%';
                document.getElementById('taskPercentLabel').innerText = '98%';
              }
            }
          } catch(e) {}
        };
      } catch (wsErr) {
        console.warn('WS not available, falling back to HTTP polling:', wsErr);
      }

      pollInterval = setInterval(async () => {
        try {
          const res = await fetch(`/api/job/status/${promptId}`);
          const data = await res.json();

          if (data.completed) {
            clearInterval(pollInterval);
            clearInterval(timerInterval);
            document.getElementById('progressBar').style.width = '100%';
            document.getElementById('taskPercentLabel').innerText = '100%';
            document.getElementById('taskStatusLabel').innerText = 'สร้างวิดีโอสำเร็จและดาวน์โหลดลงเครื่องแล้ว!';

            if (data.media && data.media.length > 0) {
              const videoObj = data.media[0];
              displayResultVideo(videoObj.url);
            } else {
              showToast('เรนเดอร์เสร็จแล้ว แต่ไม่พบไฟล์ผลลัพธ์จาก ComfyUI', 'danger');
            }

            resetGenUI();

            if (autoStopPod) {
              setTimeout(() => {
                confirmStopServer();
              }, 2000);
            }
          }
        } catch (e) {
          console.error('Polling error:', e);
        }
      }, 2500);
    }

    function displayResultVideo(url) {
      const v = document.getElementById('resultVideo');
      const placeholder = document.getElementById('videoPlaceholder');
      const downloadBtn = document.getElementById('btnDownload');

      v.src = url;
      v.classList.remove('hidden');
      placeholder.classList.add('hidden');

      downloadBtn.href = url;
      downloadBtn.classList.remove('hidden');
      v.play().catch(() => {});
    }

    function resetGenUI() {
      const btnGen = document.getElementById('btnGenerate');
      btnGen.disabled = false;
      btnGen.innerHTML = '<i class="fa-solid fa-play"></i> <span>เริ่มสร้างวิดีโอ (Generate MiniMax H3 Video)</span>';
    }
  </script>
</body>
</html>
"""

FRONTEND_DIR = BASE_DIR / "frontend"
if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")

@app.get("/")
def serve_index():
    return HTMLResponse(content=HTML_PAGE)

