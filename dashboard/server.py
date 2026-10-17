"""
Text-to-CAD Studio Dashboard Server
Powered by Groq AI for intelligent prompt polishing & parametric CAD synthesis.
Compiles STEP & STL via cadgen/build123d engine.
"""

import os
import sys
import json
import uuid
import time
import re
import subprocess
from pathlib import Path
from typing import Optional, Dict, Any, List
from dotenv import load_dotenv

# Load .env variables
load_dotenv(Path(__file__).resolve().parent.parent / ".env")
load_dotenv()

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

try:
    from groq import Groq
    GROQ_AVAILABLE = True
except ImportError:
    GROQ_AVAILABLE = False

BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent
PROJECTS_DIR = BASE_DIR / "projects"
STATIC_DIR = BASE_DIR / "static"

PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
STATIC_DIR.mkdir(parents=True, exist_ok=True)

# Find python executable (prefer local .venv)
PYTHON_EXE = str(PROJECT_ROOT / ".venv" / "Scripts" / "python.exe")
if not os.path.exists(PYTHON_EXE):
    PYTHON_EXE = str(PROJECT_ROOT / ".venv" / "bin" / "python")
if not os.path.exists(PYTHON_EXE):
    PYTHON_EXE = sys.executable

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")

app = FastAPI(title="Text-to-CAD Studio Dashboard")


def get_groq_client(override_key: Optional[str] = None):
    key = override_key or GROQ_API_KEY
    if not key or not GROQ_AVAILABLE:
        return None
    return Groq(api_key=key)


class PolishRequest(BaseModel):
    prompt: str
    existing_spec: Optional[str] = None
    existing_code: Optional[str] = None
    apiKey: Optional[str] = None
    model: Optional[str] = None


class GenerateRequest(BaseModel):
    project_id: Optional[str] = None
    prompt: str
    polished_spec: str
    code: Optional[str] = None
    parameters: Optional[Dict[str, float]] = None
    apiKey: Optional[str] = None


class EditRequest(BaseModel):
    project_id: str
    edit_instruction: str
    current_code: str
    current_spec: str
    apiKey: Optional[str] = None


def parse_parameters_from_code(code: str) -> Dict[str, float]:
    """Extract top-level numeric parameters from Python code."""
    params = {}
    for line in code.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("@") or line.startswith("def "):
            continue
        if "=" in line:
            parts = line.split("=", 1)
            name = parts[0].strip()
            val_str = parts[1].split("#")[0].strip()
            if name.isupper() or any(k in name.lower() for k in ["length", "width", "height", "dia", "rad", "thick", "radius"]):
                try:
                    val = float(val_str)
                    params[name] = val
                except ValueError:
                    pass
    return params


def extract_python_code(text: str) -> str:
    """Extract code from markdown code fences or return raw text."""
    pattern = r"```(?:python)?\s*([\s\S]*?)```"
    matches = re.findall(pattern, text)
    if matches:
        return matches[0].strip()
    return text.strip()


def generate_spec_with_groq(prompt: str, client: Any, model: str) -> str:
    """Use Groq LLM to convert a brief prompt into an engineering specification."""
    sys_prompt = """You are a Principal Mechanical Engineer and CAD Systems Architect.
Your task is to take any user prompt and expand it into a comprehensive, highly technical engineering specification ready for parametric 3D CAD modeling.

Structure your response with:
1. Executive Summary & Functional Intent
2. Coordinate Datums & Orientation
3. Key Parametric Dimensions (all in millimeters mm, explicit nominal values, wall thicknesses >= 3mm)
4. Fastener & Interface Standards (clearance holes for M3/M4/M5, counterbores, tolerances)
5. Design for Manufacturing (DFM) & 3D Printability (overhang angles, self-supporting geometry, fillets)

Keep it dense, precise, and professional. Avoid conversational filler."""

    resp = client.chat.completions.create(
        messages=[
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": f"Create technical CAD engineering specification for:\n{prompt}"}
        ],
        model=model,
        max_tokens=800,
        temperature=0.3
    )
    return resp.choices[0].message.content


def generate_code_with_groq(prompt: str, spec: str, client: Any, model: str) -> str:
    """Use Groq LLM to write build123d code with @step and @stl decorators."""
    sys_prompt = """You are an expert build123d and CAD developer.
Write a COMPLETE, VALID Python script using `build123d` and `cadgen`.
Rules:
- Import: `from cadgen import build123d as bd`
- Import: `from cadgen import step, stl`
- Define uppercase numeric constants at the top (e.g. LENGTH = 60.0, WIDTH = 30.0).
- Decorate the function with `@stl(out="model.stl")` and `@step(out="model.step")`.
- Inside the function, construct 3D shapes using clean algebraic operations (+, -, *, bd.Pos, bd.Rotation, bd.Cylinder, bd.Box).
- Set `part.label = "..."` and return the shape.
- End with `if __name__ == "__main__": <function_name>()`.
- Output ONLY the Python code block, no markdown explanations."""

    resp = client.chat.completions.create(
        messages=[
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": f"User Prompt: {prompt}\n\nTechnical Spec:\n{spec}\n\nWrite the Python build123d script."}
        ],
        model=model,
        max_tokens=1000,
        temperature=0.2
    )
    return extract_python_code(resp.choices[0].message.content)


def edit_code_with_groq(current_code: str, edit_instruction: str, client: Any, model: str) -> str:
    """Use Groq LLM to apply conversational revisions to build123d code."""
    sys_prompt = """You are an expert build123d CAD engineer.
Modify the existing Python CAD script according to the user's revision instruction.
Preserve all decorator conventions (`@stl(out="model.stl")`, `@step(out="model.step")`) and constants.
Return ONLY the updated Python code."""

    resp = client.chat.completions.create(
        messages=[
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": f"Existing Code:\n```python\n{current_code}\n```\n\nRevision Instruction:\n{edit_instruction}"}
        ],
        model=model,
        max_tokens=1200,
        temperature=0.2
    )
    return extract_python_code(resp.choices[0].message.content)


# Built-in robust fallback template generator
def synthesize_cad_fallback(prompt: str, spec: str) -> str:
    prompt_lower = (prompt + " " + spec).lower()

    if "pulley" in prompt_lower or "timing" in prompt_lower or "gear" in prompt_lower:
        return '''"""Parametric Timing Pulley with Bore & Flanges."""
from cadgen import build123d as bd
from cadgen import step, stl
import math

PITCH_DIA = 32.0
TEETH_COUNT = 20
BORE_DIA = 5.0
TOOTH_DEPTH = 1.2
FLANGE_DIA = 36.0
FLANGE_THICK = 1.5
BELT_WIDTH = 8.0
TOTAL_HEIGHT = 15.0

@stl(out="model.stl")
@step(out="model.step")
def timing_pulley():
    body = bd.Cylinder(radius=PITCH_DIA / 2, height=TOTAL_HEIGHT)
    bottom_flange = bd.Pos(0, 0, -(TOTAL_HEIGHT - FLANGE_THICK) / 2) * bd.Cylinder(radius=FLANGE_DIA / 2, height=FLANGE_THICK)
    top_flange = bd.Pos(0, 0, (TOTAL_HEIGHT - FLANGE_THICK) / 2) * bd.Cylinder(radius=FLANGE_DIA / 2, height=FLANGE_THICK)
    body = body + bottom_flange + top_flange
    bore = bd.Cylinder(radius=BORE_DIA / 2, height=TOTAL_HEIGHT * 2)
    body -= bore
    for i in range(int(TEETH_COUNT)):
        angle = (2 * math.pi / TEETH_COUNT) * i
        x = (PITCH_DIA / 2) * math.cos(angle)
        y = (PITCH_DIA / 2) * math.sin(angle)
        tooth_cutter = bd.Pos(x, y, 0) * bd.Cylinder(radius=TOOTH_DEPTH, height=BELT_WIDTH)
        body -= tooth_cutter
    body.label = "timing_pulley"
    return body

if __name__ == "__main__":
    timing_pulley()
'''
    elif "enclosure" in prompt_lower or "case" in prompt_lower or "box" in prompt_lower:
        return '''"""Parametric Electronics Enclosure with Internal Standoffs."""
from cadgen import build123d as bd
from cadgen import step, stl

LENGTH = 90.0
WIDTH = 60.0
HEIGHT = 28.0
WALL_THICKNESS = 2.5
STANDOFF_HEIGHT = 6.0
STANDOFF_DIA = 6.0
STANDOFF_HOLE = 2.8

@stl(out="model.stl")
@step(out="model.step")
def electronics_enclosure():
    outer = bd.Box(LENGTH, WIDTH, HEIGHT)
    inner = bd.Pos(0, 0, WALL_THICKNESS / 2) * bd.Box(
        LENGTH - 2 * WALL_THICKNESS,
        WIDTH - 2 * WALL_THICKNESS,
        HEIGHT - WALL_THICKNESS + 1.0
    )
    enclosure = outer - inner
    dx = (LENGTH - 2 * WALL_THICKNESS) / 2 - 8.0
    dy = (WIDTH - 2 * WALL_THICKNESS) / 2 - 8.0
    z_pos = -HEIGHT / 2 + WALL_THICKNESS + STANDOFF_HEIGHT / 2
    for sx in [-dx, dx]:
        for sy in [-dy, dy]:
            standoff = bd.Pos(sx, sy, z_pos) * bd.Cylinder(radius=STANDOFF_DIA / 2, height=STANDOFF_HEIGHT)
            hole = bd.Pos(sx, sy, z_pos + 1.0) * bd.Cylinder(radius=STANDOFF_HOLE / 2, height=STANDOFF_HEIGHT * 1.5)
            enclosure = (enclosure + standoff) - hole
    enclosure.label = "electronics_enclosure"
    return enclosure

if __name__ == "__main__":
    electronics_enclosure()
'''
    else:
        return '''"""Parametric Structural Mounting Bracket."""
from cadgen import build123d as bd
from cadgen import step, stl

BASE_LENGTH = 65.0
BASE_WIDTH = 35.0
WALL_HEIGHT = 35.0
THICKNESS = 5.0
HOLE_DIA = 5.5

@stl(out="model.stl")
@step(out="model.step")
def mounting_bracket():
    base = bd.Box(BASE_LENGTH, BASE_WIDTH, THICKNESS)
    wall = bd.Pos(-(BASE_LENGTH - THICKNESS) / 2, 0, (WALL_HEIGHT - THICKNESS) / 2) * bd.Box(
        THICKNESS, BASE_WIDTH, WALL_HEIGHT
    )
    bracket = base + wall
    for offset_x in [BASE_LENGTH / 6, BASE_LENGTH / 3]:
        hole_base = bd.Pos(offset_x, 0, 0) * bd.Cylinder(radius=HOLE_DIA / 2, height=THICKNESS * 2)
        bracket -= hole_base
    hole_wall = bd.Pos(-(BASE_LENGTH - THICKNESS) / 2, 0, WALL_HEIGHT / 2) * (
        bd.Rotation(0, 90, 0) * bd.Cylinder(radius=HOLE_DIA / 2, height=THICKNESS * 2)
    )
    bracket -= hole_wall
    bracket.label = "mounting_bracket"
    return bracket

if __name__ == "__main__":
    mounting_bracket()
'''


@app.get("/api/config")
async def get_config():
    """Return AI engine status and active Groq model."""
    client = get_groq_client()
    return {
        "groq_configured": bool(client),
        "groq_model": GROQ_MODEL,
        "cadgen_ready": True,
    }


@app.post("/api/polish-prompt")
async def polish_prompt(req: PolishRequest):
    """Refine user prompt into an engineering spec using Groq AI."""
    raw = req.prompt.strip()
    if not raw:
        raise HTTPException(status_code=400, detail="Prompt cannot be empty")

    client = get_groq_client(req.apiKey)
    model = req.model or GROQ_MODEL

    if client:
        try:
            polished = generate_spec_with_groq(raw, client, model)
            provider = f"Groq ({model})"
        except Exception as e:
            # Fallback if Groq has an issue
            polished = f"# Engineering Specification: {raw[:35]}\n\n## 1. Functional Intent\n- Design goal: {raw}\n- Standard datum on XY plane.\n\n## 2. Key Dimensions\n- Defined in mm, solid watertight geometry.\n\n(Fallback: {str(e)})"
            provider = "Built-in Rule Fallback"
    else:
        polished = f"# Engineering Specification: {raw[:35]}\n\n## 1. Functional Intent\n- Design goal: {raw}\n- Standard datum on XY plane.\n\n## 2. Key Dimensions\n- Solid watertight geometry parameterized in mm."
        provider = "Built-in"

    title_words = [w.capitalize() for w in raw.split()[:4]]
    title = " ".join(title_words) or "Custom Mechanical Component"

    return {
        "title": title,
        "original_prompt": raw,
        "polished_spec": polished,
        "provider": provider,
        "timestamp": time.time(),
    }


@app.post("/api/generate-cad")
async def generate_cad(req: GenerateRequest):
    """Synthesizes build123d code with Groq and compiles it into STEP & STL via cadgen."""
    project_id = req.project_id or f"proj_{uuid.uuid4().hex[:8]}"
    project_dir = PROJECTS_DIR / project_id
    project_dir.mkdir(parents=True, exist_ok=True)

    client = get_groq_client(req.apiKey)
    model = GROQ_MODEL

    code = req.code
    # If no custom code is provided, generate via Groq or fallback template
    if not code or len(code.strip()) < 10:
        if client:
            try:
                code = generate_code_with_groq(req.prompt, req.polished_spec, client, model)
            except Exception:
                code = synthesize_cad_fallback(req.prompt, req.polished_spec)
        else:
            code = synthesize_cad_fallback(req.prompt, req.polished_spec)

    # Apply parameter tweaks if provided
    if req.parameters:
        lines = code.splitlines()
        updated_lines = []
        for line in lines:
            changed = False
            if "=" in line and not line.strip().startswith("def ") and not line.strip().startswith("@"):
                name = line.split("=")[0].strip()
                if name in req.parameters:
                    updated_lines.append(f"{name} = {req.parameters[name]}")
                    changed = True
            if not changed:
                updated_lines.append(line)
        code = "\n".join(updated_lines)

    # Save script to project directory
    model_py = project_dir / "model.py"
    model_py.write_text(code, encoding="utf-8")

    # Execute build via python model.py
    start_time = time.time()
    try:
        proc = subprocess.run(
            [PYTHON_EXE, "model.py"],
            cwd=str(project_dir),
            capture_output=True,
            text=True,
            timeout=35,
        )
        build_log = proc.stdout + ("\n" + proc.stderr if proc.stderr else "")
        success = (proc.returncode == 0) and (project_dir / "model.stl").exists()
    except Exception as e:
        build_log = f"Execution error: {str(e)}"
        success = False

    # If first compile had a minor geometry error and Groq is available, attempt self-repair
    if not success and client:
        try:
            repair_prompt = f"The following build123d code failed to compile with error:\n{build_log[:300]}\n\nFix the code and return only working Python:\n```python\n{code}\n```"
            repaired_code = extract_python_code(
                client.chat.completions.create(
                    messages=[{"role": "user", "content": repair_prompt}],
                    model=model,
                    max_tokens=1000
                ).choices[0].message.content
            )
            model_py.write_text(repaired_code, encoding="utf-8")
            proc2 = subprocess.run(
                [PYTHON_EXE, "model.py"],
                cwd=str(project_dir),
                capture_output=True,
                text=True,
                timeout=35,
            )
            if proc2.returncode == 0 and (project_dir / "model.stl").exists():
                code = repaired_code
                build_log = "Auto-repaired by Groq:\n" + proc2.stdout
                success = True
        except Exception:
            pass

    elapsed = round(time.time() - start_time, 2)

    meta = {
        "id": project_id,
        "title": req.prompt[:32].strip() or "CAD Model",
        "prompt": req.prompt,
        "polished_spec": req.polished_spec,
        "success": success,
        "elapsed": elapsed,
        "parameters": parse_parameters_from_code(code),
        "created_at": time.time(),
        "has_stl": (project_dir / "model.stl").exists(),
        "has_step": (project_dir / "model.step").exists(),
    }
    (project_dir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

    stl_url = f"/outputs/{project_id}/model.stl" if (project_dir / "model.stl").exists() else None
    step_url = f"/outputs/{project_id}/model.step" if (project_dir / "model.step").exists() else None

    return {
        "project_id": project_id,
        "success": success,
        "elapsed": elapsed,
        "build_log": build_log,
        "code": code,
        "parameters": meta["parameters"],
        "stl_url": stl_url,
        "step_url": step_url,
    }


@app.post("/api/edit-cad")
async def edit_cad(req: EditRequest):
    """Applies conversational edit to existing CAD model using Groq AI."""
    project_dir = PROJECTS_DIR / req.project_id
    if not project_dir.exists():
        raise HTTPException(status_code=404, detail="Project not found")

    client = get_groq_client(req.apiKey)
    model = GROQ_MODEL

    if client:
        try:
            updated_code = edit_code_with_groq(req.current_code, req.edit_instruction, client, model)
        except Exception:
            updated_code = req.current_code
    else:
        updated_code = req.current_code

    updated_spec = req.current_spec + f"\n- **Revision**: {req.edit_instruction}"

    gen_req = GenerateRequest(
        project_id=req.project_id,
        prompt=req.edit_instruction,
        polished_spec=updated_spec,
        code=updated_code,
        apiKey=req.apiKey,
    )
    return await generate_cad(gen_req)


@app.get("/api/projects")
async def list_projects():
    """List all saved projects."""
    projects = []
    for p in sorted(PROJECTS_DIR.iterdir(), key=os.path.getmtime, reverse=True):
        if p.is_dir() and (p / "meta.json").exists():
            try:
                data = json.loads((p / "meta.json").read_text(encoding="utf-8"))
                projects.append(data)
            except Exception:
                pass
    return projects


@app.get("/api/project/{project_id}")
async def get_project(project_id: str):
    """Retrieve full details of a project."""
    project_dir = PROJECTS_DIR / project_id
    if not project_dir.exists() or not (project_dir / "meta.json").exists():
        raise HTTPException(status_code=404, detail="Project not found")

    meta = json.loads((project_dir / "meta.json").read_text(encoding="utf-8"))
    code = (project_dir / "model.py").read_text(encoding="utf-8") if (project_dir / "model.py").exists() else ""
    meta["code"] = code
    meta["stl_url"] = f"/outputs/{project_id}/model.stl" if (project_dir / "model.stl").exists() else None
    meta["step_url"] = f"/outputs/{project_id}/model.step" if (project_dir / "model.step").exists() else None
    return meta


@app.get("/api/download/{project_id}/{file_type}")
async def download_file(project_id: str, file_type: str):
    """Download generated artifacts (.stl, .step, .py)."""
    project_dir = PROJECTS_DIR / project_id
    filename = f"model.{file_type}"
    target = project_dir / filename
    if not target.exists():
        raise HTTPException(status_code=404, detail=f"File {filename} not found")
    return FileResponse(path=str(target), filename=f"{project_id}_{filename}", media_type="application/octet-stream")


@app.get("/outputs/{project_id}/{filename}")
async def serve_output(project_id: str, filename: str):
    """Serve output artifacts with CORS for 3D canvas loading."""
    target = PROJECTS_DIR / project_id / filename
    if not target.exists():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(path=str(target), headers={"Access-Control-Allow-Origin": "*"})


# Serve frontend static assets
app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    host = os.getenv("HOST", "0.0.0.0")
    uvicorn.run(app, host=host, port=port)
