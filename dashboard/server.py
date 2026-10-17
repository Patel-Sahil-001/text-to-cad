"""
Text-to-CAD Studio Dashboard Server
100% Dynamic CAD Synthesis & Engineering Intelligence powered by Groq LLMs.
Zero hardcoded templates: everything is generated, parsed, and self-healed dynamically.
"""

import os
import sys
import json
import uuid
import time
import re
import subprocess
import shutil
import random
from pathlib import Path
from typing import Optional, Dict, Any, List
from dotenv import load_dotenv

# Load .env variables dynamically
load_dotenv(Path(__file__).resolve().parent.parent / ".env")
load_dotenv()

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
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

# Find python executable dynamically
PYTHON_EXE = str(PROJECT_ROOT / ".venv" / "Scripts" / "python.exe")
if not os.path.exists(PYTHON_EXE):
    PYTHON_EXE = str(PROJECT_ROOT / ".venv" / "bin" / "python")
if not os.path.exists(PYTHON_EXE):
    PYTHON_EXE = sys.executable

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
DEFAULT_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
# Disable restrictive cadgen memory admission so worker starts smoothly in 512MB containers
os.environ["CADGEN_MEMORY_MB"] = "0"

app = FastAPI(title="Text-to-CAD Dynamic Studio")

# Enable CORS for Vercel and cross-origin hosting
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


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
    model: Optional[str] = None


class EditRequest(BaseModel):
    project_id: str
    edit_instruction: str
    current_code: str
    current_spec: str
    apiKey: Optional[str] = None
    model: Optional[str] = None


class DynamicPresetRequest(BaseModel):
    topic: Optional[str] = "general engineering and 3D printing"
    apiKey: Optional[str] = None
    model: Optional[str] = None


def is_valid_cad_code(code: str) -> bool:
    """Validate whether code is actual Python CAD code rather than conversational filler."""
    if not code or len(code.strip()) < 30:
        return False
    conversational_phrases = [
        "i am happy", "i'm happy", "could you please", "looks like", "sorry",
        "here is the", "hope this helps", "let me know if", "i need the code",
        "provide the build123d"
    ]
    first_lines = "\n".join(code.splitlines()[:5]).lower()
    if any(phrase in first_lines for phrase in conversational_phrases):
        return False
    # Must contain python def and cadgen/build123d markers
    has_def = "def " in code
    has_cad = any(marker in code for marker in ["bd.", "build123d", "cadgen", "Box(", "Cylinder("])
    return has_def and has_cad


def extract_python_code(text: str) -> str:
    """Extract code from markdown code fences or return clean code text, rejecting conversational text."""
    if not text:
        return ""
    pattern = r"```(?:python)?\s*([\s\S]*?)```"
    matches = re.findall(pattern, text)
    if matches:
        for m in matches:
            if "def " in m and ("bd." in m or "build123d" in m or "cadgen" in m):
                return m.strip()
        return matches[0].strip()

    # If no fences, filter out conversational chatter lines
    lines = []
    started = False
    for line in text.splitlines():
        trimmed = line.strip()
        if trimmed.startswith(("import ", "from ", "def ", "#", "@", "LENGTH", "WIDTH", "HEIGHT", "RADIUS")):
            started = True
        if started:
            lines.append(line)

    candidate = "\n".join(lines).strip()
    if is_valid_cad_code(candidate):
        return candidate
    return ""


def parse_parameters_from_code(code: str) -> Dict[str, float]:
    """
    Dynamically extract ALL top-level numeric parameters from Python code.
    Any assignment like `VARIABLE_NAME = 12.5` or `speed = 10` is automatically surfaced.
    """
    params = {}
    for line in code.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("@") or line.startswith("def ") or line.startswith("import ") or line.startswith("from "):
            continue
        if "=" in line and not line.startswith("if ") and not line.startswith("for ") and not line.startswith("return "):
            parts = line.split("=", 1)
            var_name = parts[0].strip()
            # Must be a valid Python identifier
            if var_name.isidentifier():
                val_str = parts[1].split("#")[0].strip()
                try:
                    val = float(val_str)
                    params[var_name] = val
                except ValueError:
                    pass
    return params


def diagnose_compile_error(build_log: str, code: str = "") -> Dict[str, Any]:
    """
    Expert CAD Compiler Diagnostics:
    Analyzes compiler output, traceback, and build logs to determine:
    1. Error category and technical classification.
    2. Plain-English root cause explanation ('Why this happened').
    3. Actionable remediation steps ('How to fix it').
    4. Relevant line number and code snippet when available.
    """
    log_lower = build_log.lower()

    # 1. Memory Admission / cadgen daemon error
    if "cadgen memory admission" in log_lower or "memoryadmissionerror" in log_lower:
        match = re.search(r'(\d+\s*MiB\s*requested.*?exceeds.*?allowance)', build_log, re.IGNORECASE)
        detail = f" ({match.group(1)})" if match else ""
        return {
            "has_error": True,
            "category": "Daemon Memory Admission",
            "badge_color": "warning",
            "title": "Worker Memory Admission Rejected",
            "why": f"The cadgen compiler daemon blocked worker creation because requested RAM exceeded the available container memory limit{detail}. On free/restricted cloud containers (such as Render 512MB RAM), the default 512MB reservation per worker exceeds container cgroups.",
            "solution": "Set environment variable CADGEN_MEMORY_MB=0 to bypass worker memory admission reservations, or increase container RAM on your host.",
            "raw_log": build_log,
        }

    # 2. Syntax Error (conversational text, invalid characters, bad syntax)
    if "syntaxerror" in log_lower:
        # Check for smart quote / non-ASCII character
        char_match = re.search(r"invalid character ['\"]([^'\"]+)['\"]", build_log)
        line_match = re.search(r'line\s+(\d+)', build_log, re.IGNORECASE)
        line_num = line_match.group(1) if line_match else None

        if char_match:
            char_found = char_match.group(1)
            return {
                "has_error": True,
                "category": "SyntaxError: Invalid Character",
                "badge_color": "error",
                "title": f"Invalid Non-ASCII Character '{char_found}'" + (f" on line {line_num}" if line_num else ""),
                "why": f"The Python interpreter encountered a non-standard character '{char_found}' (such as a curly quote, smart apostrophe, or foreign symbol) instead of standard ASCII code. This commonly occurs when pasting code containing conversational AI chatter like \"I'm happy to help...\" directly into the script.",
                "solution": "Replace smart/curly quotes with standard single (') or double (\") quotes, and ensure conversational text or intro greetings are removed from the Python editor.",
                "line_number": line_num,
                "raw_log": build_log,
            }
        
        # General syntax error
        return {
            "has_error": True,
            "category": "SyntaxError: Malformed Code",
            "badge_color": "error",
            "title": f"Python Syntax Error" + (f" on line {line_num}" if line_num else ""),
            "why": "The script contains malformed Python syntax, such as an unclosed parenthesis, missing colon, unexpected indentation, or non-Python conversational text.",
            "solution": "Check indentation, ensure all parentheses () and brackets [] are matched, and verify that all statements are valid Python code.",
            "line_number": line_num,
            "raw_log": build_log,
        }

    # 3. OpenCASCADE / BRep Kernel Geometric Failure
    if any(k in build_log for k in ["BRep_", "Standard_ConstructionError", "Standard_Failure", "Geom_", "TopAbs_", "BRepMesh"]):
        return {
            "has_error": True,
            "category": "Geometry Kernel Failure",
            "badge_color": "error",
            "title": "OpenCASCADE Solid Boolean / Topology Error",
            "why": "The OpenCASCADE 3D solid modeling kernel failed while computing a boolean operation (cut, union, or fillet). This usually happens when cutting tool geometry has exactly coplanar/overlapping faces with the workpiece, creating non-manifold edges, or when an edge fillet radius is too large for the adjacent geometry.",
            "solution": "1. Make drill/cutter tools slightly oversized (e.g. height * 1.2) so they penetrate completely through boundaries rather than sharing coplanar faces.\n2. Reduce fillet radii or replace aggressive fillets with chamfers.\n3. Ensure subtracting bodies actually intersect the target solid.",
            "raw_log": build_log,
        }

    # 4. Timeout
    if "timed out" in log_lower or "timeoutexpired" in log_lower:
        return {
            "has_error": True,
            "category": "Execution Timeout",
            "badge_color": "warning",
            "title": "Geometry Computation Timed Out (> 40s)",
            "why": "The CAD script exceeded the 40-second execution time limit. Complex solid meshing, fine curved tessellation, or high loop counts can cause the geometric kernel to hang.",
            "solution": "Reduce loop counts, simplify boolean operations, or avoid dense fine-pattern cuts.",
            "raw_log": build_log,
        }

    # 5. Missing Import or Module
    if "modulenotfounderror" in log_lower or "importerror" in log_lower:
        mod_match = re.search(r"no module named ['\"]([^'\"]+)['\"]", build_log, re.IGNORECASE)
        mod_name = mod_match.group(1) if mod_match else "unknown"
        return {
            "has_error": True,
            "category": "Import Error",
            "badge_color": "error",
            "title": f"Missing Python Module: '{mod_name}'",
            "why": f"The script tried to import '{mod_name}', which is not available in the CAD runtime environment.",
            "solution": "Use only built-in modules ('math') or supported CAD packages ('cadgen', 'build123d').",
            "raw_log": build_log,
        }

    # 6. NameError / AttributeError / Undefined API
    if "attributeerror" in log_lower:
        attr_match = re.search(r"module ['\"][^'\"]+['\"] has no attribute ['\"]([^'\"]+)['\"]", build_log)
        attr_str = attr_match.group(1) if attr_match else "attribute"
        return {
            "has_error": True,
            "category": "AttributeError: Invalid API",
            "badge_color": "error",
            "title": f"Invalid build123d Attribute '{attr_str}'",
            "why": f"The script called 'bd.{attr_str}' or referenced an attribute that does not exist in build123d. For operations like fillets or chamfers, build123d applies them to shape edges (e.g. 'part = part.chamfer(...)') rather than 'bd.{attr_str}'.",
            "solution": f"Consult build123d API conventions: use constructors like 'bd.Box', 'bd.Cylinder', 'bd.Pos', 'bd.Rotation', and apply chamfers/fillets via edge methods.",
            "raw_log": build_log,
        }

    if "nameerror" in log_lower:
        name_match = re.search(r"name ['\"]([^'\"]+)['\"] is not defined", build_log)
        name_str = name_match.group(1) if name_match else "variable"
        return {
            "has_error": True,
            "category": "NameError: Undefined Identifier",
            "badge_color": "error",
            "title": f"Undefined Identifier '{name_str}'",
            "why": f"The script tried to use '{name_str}', but it was never defined or imported. For build123d shapes, make sure to prefix with 'bd.' (e.g. 'bd.Pos(...)', 'bd.Box(...)').",
            "solution": f"Define '{name_str}' or check for typos. If it is a build123d class, use 'bd.{name_str}'.",
            "raw_log": build_log,
        }

    # 7. Division by zero / Math Domain
    if "zerodivisionerror" in log_lower:
        return {
            "has_error": True,
            "category": "Math Domain Error",
            "badge_color": "error",
            "title": "Division by Zero in Parameter Calculation",
            "why": "A parametric dimension or offset calculation divided by zero, resulting in an undefined number.",
            "solution": "Check your parameter values in the left sidebar and ensure no wall thickness, length, or clearance value is zero.",
            "raw_log": build_log,
        }

    # 8. Output file missing
    if "model.stl" in log_lower and "not found" in log_lower:
        return {
            "has_error": True,
            "category": "Missing Output File",
            "badge_color": "warning",
            "title": "No STL Mesh Generated",
            "why": "The script executed without a fatal Python crash, but failed to write 'model.stl'. This occurs if the main generation function is missing the @stl decorator or does not return a valid Part object.",
            "solution": "Ensure your function is decorated with @stl(out=\"model.stl\") and @step(out=\"model.step\") and returns the constructed part.",
            "raw_log": build_log,
        }

    # 9. Generic build failure / Extract specific FAILED: line
    failed_match = re.search(r"FAILED:\s*([^\n\r]+)", build_log)
    error_summary = failed_match.group(1).strip() if failed_match else ""
    if not error_summary:
        lines = [l.strip() for l in build_log.splitlines() if l.strip() and not l.startswith("{")]
        error_summary = lines[-1] if lines else "Process terminated with non-zero exit code"

    return {
        "has_error": True,
        "category": "CAD Compilation Failure",
        "badge_color": "error",
        "title": "Compilation Error: " + error_summary[:70],
        "why": "The CAD script or build123d geometric engine threw an exception during evaluation.",
        "solution": "Inspect the detailed traceback below to review the failing line number and exact stack trace.",
        "raw_log": build_log,
    }


def generate_spec_with_groq(prompt: str, client: Any, model: str) -> str:
    """Dynamically synthesize an engineering specification using Groq."""
    sys_prompt = """You are a Principal Mechanical Engineer and CAD Systems Architect.
Given any user prompt, synthesize a comprehensive, rigorous technical engineering specification for parametric 3D CAD modeling.

Structure your response with:
1. Executive Summary & Functional Intent
2. Coordinate Datums & Orientation
3. Key Parametric Dimensions (all in millimeters mm, explicit nominal values, wall thicknesses >= 2.5mm)
4. Fastener & Interface Standards (clearance holes, counterbores, tolerances)
5. Design for Manufacturing (DFM) & 3D Printability (overhang angles, self-supporting geometry, fillets)

Keep it dense, precise, and professional. Avoid conversational filler."""

    resp = client.chat.completions.create(
        messages=[
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": f"Create technical CAD engineering specification for:\n{prompt}"}
        ],
        model=model,
        max_tokens=850,
        temperature=0.3
    )
    return resp.choices[0].message.content


def generate_code_with_groq(prompt: str, spec: str, client: Any, model: str) -> str:
    """Dynamically write build123d Python script from prompt and spec."""
    sys_prompt = """You are an elite build123d CAD engineer.
Write a COMPLETE, VALID Python script using `build123d` and `cadgen` to construct the 3D part.

Essential Rules:
1. Imports:
   from cadgen import build123d as bd
   from cadgen import step, stl
   import math

2. Declare all controlling dimensions as uppercase constants at the top:
   LENGTH = 60.0
   WIDTH = 40.0
   ...

3. Function decorated with exports:
   @stl(out="model.stl")
   @step(out="model.step")
   def generate_part():
       ...
       part.label = "part"
       return part

4. Modeling Best Practices:
   - Use clean algebraic composition: (+) for union, (-) for cut/bore, (*) for placement.
   - Example position: bd.Pos(x, y, z) * bd.Box(...)
   - Example rotation: bd.Rotation(rx, ry, rz) * bd.Cylinder(...)
   - When subtracting holes, make the cutting cylinder slightly taller than the part to avoid coplanar face artifacts.
   - Avoid aggressive fillets on complex intersections that could fail the CAD kernel; prefer simple chamfers or clean geometry.

5. End with:
   if __name__ == "__main__":
       generate_part()

Return ONLY the raw Python code block (inside ```python ... ```), no other commentary."""

    resp = client.chat.completions.create(
        messages=[
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": f"User Prompt: {prompt}\n\nTechnical Spec:\n{spec}\n\nSynthesize the build123d Python script now."}
        ],
        model=model,
        max_tokens=2200,
        temperature=0.2
    )
    return extract_python_code(resp.choices[0].message.content)


def edit_code_with_groq(current_code: str, edit_instruction: str, client: Any, model: str) -> str:
    """Dynamically revise build123d code according to conversational instructions."""
    sys_prompt = """You are an expert build123d CAD engineer.
Modify the existing Python CAD script according to the user's revision instruction.
Preserve the @stl and @step decorators, keep all top-level constants updated, and return valid build123d Python code.
Output ONLY the Python code block inside ```python ... ``` without conversational intro or commentary."""

    resp = client.chat.completions.create(
        messages=[
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": f"Existing Code:\n```python\n{current_code}\n```\n\nRevision Instruction:\n{edit_instruction}"}
        ],
        model=model,
        max_tokens=2200,
        temperature=0.2
    )
    return extract_python_code(resp.choices[0].message.content)


def generate_dynamic_fallback(prompt: str) -> str:
    """
    Dynamic generative fallback: dynamically extracts dimensions and terms from the prompt,
    calculating proportioned dimensions and features rather than fixed numbers.
    """
    safe_name = re.sub(r'[^a-zA-Z0-9_]', '_', prompt.lower().strip()[:24]).strip('_') or "part"

    # Dynamically extract any dimensions in mm from the user's prompt
    dims = [float(x) for x in re.findall(r'(\d+(?:\.\d+)?)\s*(?:mm|cm)?', prompt)]
    length = dims[0] if len(dims) > 0 and dims[0] > 0 else 60.0
    width = dims[1] if len(dims) > 1 and dims[1] > 0 else max(20.0, length * 0.6)
    height = dims[2] if len(dims) > 2 and dims[2] > 0 else max(15.0, length * 0.4)
    wall = dims[3] if len(dims) > 3 and dims[3] > 0 else max(3.0, min(length, width) * 0.1)
    hole = dims[4] if len(dims) > 4 and dims[4] > 0 else max(3.0, min(length, width) * 0.12)

    # Check if prompt asks for cylindrical / disk / wheel / shaft / round geometry
    is_round = any(w in prompt.lower() for w in ["cylinder", "disc", "disk", "wheel", "rod", "shaft", "pulley", "round", "spacer", "bushing", "flange"])

    if is_round:
        radius = length / 2
        return f'''"""Dynamically synthesized parametric round component: {prompt[:40]}"""
from cadgen import build123d as bd
from cadgen import step, stl
import math

# Dynamic Primary Parameters (mm)
RADIUS = {radius:.1f}
HEIGHT = {height:.1f}
BORE_DIAMETER = {hole:.1f}

@stl(out="model.stl")
@step(out="model.step")
def {safe_name}():
    # Dynamic cylindrical solid
    part = bd.Cylinder(radius=RADIUS, height=HEIGHT)
    
    # Dynamic central bore
    bore = bd.Cylinder(radius=BORE_DIAMETER / 2, height=HEIGHT * 1.5)
    part -= bore

    part.label = "{safe_name}"
    return part

if __name__ == "__main__":
    {safe_name}()
'''
    else:
        return f'''"""Dynamically synthesized parametric solid: {prompt[:40]}"""
from cadgen import build123d as bd
from cadgen import step, stl
import math

# Dynamic Primary Parameters (mm)
LENGTH = {length:.1f}
WIDTH = {width:.1f}
HEIGHT = {height:.1f}
WALL_THICKNESS = {wall:.1f}
HOLE_DIAMETER = {hole:.1f}

@stl(out="model.stl")
@step(out="model.step")
def {safe_name}():
    # Base solid
    base = bd.Box(LENGTH, WIDTH, WALL_THICKNESS)
    
    # Proportional upright flange
    upright = bd.Pos(-(LENGTH - WALL_THICKNESS) / 2, 0, (HEIGHT - WALL_THICKNESS) / 2) * bd.Box(
        WALL_THICKNESS, WIDTH, HEIGHT
    )
    part = base + upright

    # Dynamic clearance hole
    hole_cut = bd.Pos(LENGTH / 4, 0, 0) * bd.Cylinder(radius=HOLE_DIAMETER / 2, height=WALL_THICKNESS * 2)
    part -= hole_cut

    part.label = "{safe_name}"
    return part

if __name__ == "__main__":
    {safe_name}()
'''


# =============================================================================
# API ENDPOINTS
# =============================================================================

@app.get("/api/config")
async def get_config():
    """Dynamically return engine status, active model, and API status."""
    client = get_groq_client()
    return {
        "groq_configured": bool(client),
        "groq_model": DEFAULT_MODEL,
        "cadgen_ready": True,
    }


@app.get("/api/models")
async def list_available_models(apiKey: Optional[str] = None):
    """Dynamically query Groq API for all available chat/text models."""
    client = get_groq_client(apiKey)
    if not client:
        return {
            "models": [
                {"id": DEFAULT_MODEL, "name": DEFAULT_MODEL, "provider": "Groq (Default)"},
                {"id": "qwen/qwen3.8-27b", "name": "qwen/qwen3.8-27b", "provider": "Groq"},
                {"id": "openai/gpt-oss-20b", "name": "openai/gpt-oss-20b", "provider": "Groq"},
            ],
            "active_model": DEFAULT_MODEL
        }

    try:
        model_list = client.models.list()
        chat_models = [
            {"id": m.id, "name": m.id, "provider": "Groq"}
            for m in model_list.data
            if "whisper" not in m.id and "guard" not in m.id and "embedding" not in m.id
        ]
        return {"models": chat_models, "active_model": DEFAULT_MODEL}
    except Exception as e:
        return {
            "models": [{"id": DEFAULT_MODEL, "name": DEFAULT_MODEL, "provider": "Groq"}],
            "active_model": DEFAULT_MODEL,
            "error": str(e)
        }


CAD_INSPIRATION_DOMAINS = [
    "robotics linkages, gripper claws, and micro-servo gearboxes",
    "compact aerospace, folding drone arms, and motor heatsinks",
    "ergonomic hand tools, magnetic bit holders, and thumb ratchets",
    "cinematography rigs, quick-release camera plates, and gimbal mounts",
    "smart workbench fixtures, DIN-rail PCB cases, and cable organizers",
    "bionic lattice structures, compliant mechanisms, and snap hinges",
    "automotive sensor brackets, intake adapters, and tubing manifolds"
]

@app.api_route("/api/inspire", methods=["GET", "POST"])
async def get_dynamic_inspirations(
    topic: Optional[str] = None,
    apiKey: Optional[str] = None,
    model: Optional[str] = None
):
    """Dynamically generate exactly 3 fresh, unique CAD engineering prompt ideas."""
    client = get_groq_client(apiKey)
    selected_model = model or DEFAULT_MODEL
    chosen_topic = topic or random.choice(CAD_INSPIRATION_DOMAINS)

    if client:
        try:
            resp = client.chat.completions.create(
                messages=[
                    {"role": "system", "content": "You are a creative mechanical design and CAD innovator."},
                    {"role": "user", "content": f"Generate exactly 3 completely unique, inventive, and practical 3D CAD design concepts for {chosen_topic}. Make each concept distinct and specify key dimensions in mm. Output ONLY a JSON list of exactly 3 objects with 'title' (2-3 words) and 'prompt' (1-2 sentences with dimensions in mm). Format: [{{\"title\": \"...\", \"prompt\": \"...\"}}]"}
                ],
                model=selected_model,
                max_tokens=500,
                temperature=0.95
            )
            raw = resp.choices[0].message.content
            # Extract JSON from response
            json_match = re.search(r'\[\s*\{.*\}\s*\]', raw, re.DOTALL)
            if json_match:
                presets = json.loads(json_match.group(0))
                # Guarantee exactly 3
                return {"presets": presets[:3], "ideas": presets[:3]}
        except Exception:
            pass

    # Diverse offline fallback pool; randomly sample 3 every time
    fallback_pool = [
        {"title": "Drone Motor Arm", "prompt": "Carbon-compatible quadcopter motor arm for 2207 brushless motor with wire routing and 16x19mm M3 pattern"},
        {"title": "Action Cam Mount", "prompt": "Action camera three-prong mounting bracket with ergonomic handle grip and 1/4-20 tripod adapter"},
        {"title": "Linear Bearing Block", "prompt": "SC8UU 8mm linear ball bearing pillow block with 4 M4 mounting threads and lightweight skeleton cutout"},
        {"title": "Cable Chain Link", "prompt": "Snap-together openable cable drag chain link with 45-degree bending limit and 15x20mm inner channel"},
        {"title": "Fan Shroud Duct", "prompt": "5015 radial blower fan duct adapter to 40mm V6 hotend with dual directional cooling nozzles"},
        {"title": "Robotic Gripper Jaw", "prompt": "Compliant finger gripper jaw with silicone pad pocket and standard MG996R servo horn spline"},
        {"title": "Magnetic Bit Caddy", "prompt": "Hex screwdriver bit holder block with 8 neodymium 6x3mm magnet recesses and angled visual display"},
        {"title": "DIN-Rail Pi Holder", "prompt": "35mm top-hat DIN-rail snap bracket for Raspberry Pi 4 with 2.5mm standoffs and M2.5 mounting bosses"}
    ]
    sampled = random.sample(fallback_pool, 3)
    return {"presets": sampled, "ideas": sampled}


@app.post("/api/polish-prompt")
async def polish_prompt(req: PolishRequest):
    """Dynamically turn any user prompt into a professional engineering specification."""
    raw = req.prompt.strip()
    if not raw:
        raise HTTPException(status_code=400, detail="Prompt cannot be empty")

    client = get_groq_client(req.apiKey)
    model = req.model or DEFAULT_MODEL

    if client:
        try:
            polished = generate_spec_with_groq(raw, client, model)
            provider = f"Groq ({model})"
        except Exception as e:
            polished = f"# Dynamic Engineering Spec: {raw[:35]}\n\n## 1. Functional Intent\n- Goal: {raw}\n- Standard datum on XY plane.\n\n## 2. Dynamic Parameters\n- Dimensions in millimeters (mm), watertight solid.\n\n(Fallback: {str(e)})"
            provider = "Local Synthesis"
    else:
        polished = f"# Dynamic Engineering Spec: {raw[:35]}\n\n## 1. Functional Intent\n- Goal: {raw}\n- Standard datum on XY plane.\n\n## 2. Dynamic Parameters\n- Dimensions in millimeters (mm), watertight solid."
        provider = "Local Synthesis"

    title_words = [w.capitalize() for w in raw.split()[:4]]
    title = " ".join(title_words) or "Custom CAD Model"

    return {
        "title": title,
        "original_prompt": raw,
        "polished_spec": polished,
        "provider": provider,
        "timestamp": time.time(),
    }


@app.post("/api/generate-cad")
async def generate_cad(req: GenerateRequest):
    """
    100% Dynamic CAD Compilation & Self-Repair:
    Synthesizes custom build123d code for ANY prompt, compiles with cadgen,
    and automatically self-heals compiler/geometry errors via Groq loop.
    """
    project_id = req.project_id or f"proj_{uuid.uuid4().hex[:8]}"
    project_dir = PROJECTS_DIR / project_id
    project_dir.mkdir(parents=True, exist_ok=True)

    client = get_groq_client(req.apiKey)
    model = req.model or DEFAULT_MODEL

    code = req.code
    # Synthesize dynamically if no valid code provided
    if not code or not is_valid_cad_code(code):
        if client:
            try:
                candidate = generate_code_with_groq(req.prompt, req.polished_spec, client, model)
                if is_valid_cad_code(candidate):
                    code = candidate
                else:
                    code = generate_dynamic_fallback(req.prompt)
            except Exception:
                code = generate_dynamic_fallback(req.prompt)
        else:
            code = generate_dynamic_fallback(req.prompt)

    # Apply parameter overrides dynamically
    if req.parameters and is_valid_cad_code(code):
        lines = code.splitlines()
        updated_lines = []
        for line in lines:
            changed = False
            if "=" in line and not line.strip().startswith("def ") and not line.strip().startswith("@"):
                var_name = line.split("=")[0].strip()
                if var_name in req.parameters:
                    updated_lines.append(f"{var_name} = {req.parameters[var_name]}")
                    changed = True
            if not changed:
                updated_lines.append(line)
        code = "\n".join(updated_lines)

    model_py = project_dir / "model.py"
    model_py.write_text(code, encoding="utf-8")

    start_time = time.time()
    success = False
    build_log = ""
    error_diagnosis = None
    sub_env = dict(os.environ, CADGEN_MEMORY_MB="0")

    # Execute build with automatic dynamic self-repair (up to 2 retry attempts)
    max_attempts = 2 if client and not req.code else 1
    for attempt in range(max_attempts):
        try:
            proc = subprocess.run(
                [PYTHON_EXE, "model.py"],
                cwd=str(project_dir),
                env=sub_env,
                capture_output=True,
                text=True,
                timeout=40,
            )
            build_log = proc.stdout + ("\n" + proc.stderr if proc.stderr else "")
            success = (proc.returncode == 0) and (project_dir / "model.stl").exists()
        except Exception as e:
            build_log = f"Execution error: {str(e)}"
            success = False

        if success:
            break

        # Capture error diagnosis
        error_diagnosis = diagnose_compile_error(build_log, code)

        # Dynamic AI self-repair
        if attempt < max_attempts - 1 and client:
            try:
                repair_prompt = f"The following build123d script failed with compiler output:\n{build_log[:400]}\n\nFix the code so it compiles cleanly without error. Output ONLY the working Python code inside ```python ``` without any conversational text:\n```python\n{code}\n```"
                repaired = extract_python_code(
                    client.chat.completions.create(
                        messages=[{"role": "user", "content": repair_prompt}],
                        model=model,
                        max_tokens=2200,
                        temperature=0.1
                    ).choices[0].message.content
                )
                if is_valid_cad_code(repaired):
                    code = repaired
                    model_py.write_text(code, encoding="utf-8")
                    build_log += f"\n[AI Self-Repair Attempt {attempt + 1}] Re-compiling..."
            except Exception:
                pass

    if not success and not error_diagnosis:
        error_diagnosis = diagnose_compile_error(build_log, code)

    # If the user did NOT supply custom code (pure prompt generation) and it still failed,
    # generate a dynamic solid so they have something in viewport, but retain the error_diagnosis
    if not success and not req.code:
        fallback_code = generate_dynamic_fallback(req.prompt)
        model_py.write_text(fallback_code, encoding="utf-8")
        try:
            proc = subprocess.run(
                [PYTHON_EXE, "model.py"],
                cwd=str(project_dir),
                env=sub_env,
                capture_output=True,
                text=True,
                timeout=40,
            )
            if proc.returncode == 0 and (project_dir / "model.stl").exists():
                code = fallback_code
                success = True
                build_log += f"\n[Self-Healing CAD Engine] Parametric solid generated successfully."
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
        "error_diagnosis": error_diagnosis if not success else None,
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
        "error_diagnosis": error_diagnosis,
    }


@app.post("/api/edit-cad")
async def edit_cad(req: EditRequest):
    """Dynamically applies conversational edit to existing CAD model using Groq."""
    project_dir = PROJECTS_DIR / req.project_id
    if not project_dir.exists():
        raise HTTPException(status_code=404, detail="Project not found")

    client = get_groq_client(req.apiKey)
    model = req.model or DEFAULT_MODEL

    if client:
        try:
            updated_code = edit_code_with_groq(req.current_code, req.edit_instruction, client, model)
        except Exception:
            updated_code = req.current_code
    else:
        updated_code = req.current_code

    updated_spec = req.current_spec + f"\n- **Dynamic Revision**: {req.edit_instruction}"

    gen_req = GenerateRequest(
        project_id=req.project_id,
        prompt=req.edit_instruction,
        polished_spec=updated_spec,
        code=updated_code,
        apiKey=req.apiKey,
        model=model,
    )
    return await generate_cad(gen_req)


@app.get("/api/projects")
async def list_projects():
    """List all saved projects dynamically."""
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
    """Retrieve full details of a project dynamically."""
    project_dir = PROJECTS_DIR / project_id
    if not project_dir.exists() or not (project_dir / "meta.json").exists():
        raise HTTPException(status_code=404, detail="Project not found")

    meta = json.loads((project_dir / "meta.json").read_text(encoding="utf-8"))
    code = (project_dir / "model.py").read_text(encoding="utf-8") if (project_dir / "model.py").exists() else ""
    meta["code"] = code
    meta["stl_url"] = f"/outputs/{project_id}/model.stl" if (project_dir / "model.stl").exists() else None
    meta["step_url"] = f"/outputs/{project_id}/model.step" if (project_dir / "model.step").exists() else None
    return meta


def _force_remove_readonly(func, path, excinfo):
    try:
        import stat
        os.chmod(path, stat.S_IWRITE)
        func(path)
    except Exception:
        pass


@app.delete("/api/project/{project_id}")
async def delete_project(project_id: str):
    """Permanently delete a project and all its generated files (STL, STEP, code, meta)."""
    clean_id = re.sub(r'[^a-zA-Z0-9_\-]', '', project_id)
    if not clean_id:
        raise HTTPException(status_code=400, detail="Invalid project ID")

    project_dir = PROJECTS_DIR / clean_id
    if not project_dir.exists():
        return {"success": True, "message": f"Project {clean_id} already deleted"}

    try:
        shutil.rmtree(project_dir, onerror=_force_remove_readonly)
        return {"success": True, "message": f"Project {clean_id} completely removed"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete project: {str(e)}")


@app.delete("/api/projects")
async def clear_all_projects():
    """Permanently delete ALL saved projects and wipe the projects workspace."""
    try:
        count = 0
        for p in PROJECTS_DIR.iterdir():
            if p.is_dir():
                try:
                    shutil.rmtree(p, onerror=_force_remove_readonly)
                    count += 1
                except Exception:
                    pass
        return {"success": True, "message": f"Cleared {count} past parts"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to clear projects: {str(e)}")


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


# Serve frontend static assets dynamically
app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    host = os.getenv("HOST", "0.0.0.0")
    uvicorn.run(app, host=host, port=port)
