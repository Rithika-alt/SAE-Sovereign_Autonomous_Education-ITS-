"""Animated lesson generator: instant HTML5 canvas explainer (replaces Manim)."""

import json
import os
import time
from pathlib import Path
from typing import Optional

from json_repair import repair_json
from langchain_ollama import ChatOllama


class AnimatedLessonGenerator:
    """Generates instant HTML5 animated lesson explainers — no subprocess, no LaTeX."""

    def __init__(self) -> None:
        self.output_dir = Path(__file__).resolve().parent / "animations"
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.llm = ChatOllama(
            base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
            model=os.getenv("OLLAMA_MODEL", "llama3.2"),
            temperature=0.3,
        )

    # ------------------------------------------------------------------
    # Public API (matches old interface so app.py callers still work)
    # ------------------------------------------------------------------

    def generate_lesson_animation(
        self,
        concept_id: str,
        lesson_text: str,
        domain: str = "",
        concepts: Optional[list] = None,
        on_complete: Optional[callable] = None,
    ) -> str:
        """Generate an HTML5 animated explainer and return its path.

        The file is written synchronously (instant — no subprocess).

        Args:
            concept_id: Module/concept identifier used for caching.
            lesson_text: Raw lesson text to extract content from.
            domain: Subject domain (optional, for richer LLM prompts).
            concepts: List of concept strings (optional).
            on_complete: Callback receiving the output path when done.

        Returns:
            Absolute path to the generated .html file.
        """
        safe_id = concept_id.lower().replace(" ", "_")
        out_path = self.output_dir / f"{safe_id}.html"

        if not out_path.exists():
            content = self._extract_content(concept_id, lesson_text)
            html = self._build_html(concept_id, content)
            out_path.write_text(html, encoding="utf-8")

        if on_complete:
            on_complete(str(out_path))
        return str(out_path)

    def generate_in_background(
        self,
        concept_id: str,
        lesson_text: str,
        domain: str = "",
        concepts: Optional[list] = None,
        on_complete: Optional[callable] = None,
    ):
        """Compatibility shim: runs synchronously (HTML5 is instant), returns None."""
        self.generate_lesson_animation(
            concept_id, lesson_text, domain, concepts, on_complete
        )
        return None

    def video_ready(self, concept_id: str) -> bool:
        """Return True if an animation already exists for this concept."""
        safe_id = concept_id.lower().replace(" ", "_")
        return (self.output_dir / f"{safe_id}.html").exists()

    def get_animation_path(self, concept_id: str) -> str:
        """Return path to animation file (may not exist yet)."""
        safe_id = concept_id.lower().replace(" ", "_")
        return str(self.output_dir / f"{safe_id}.html")

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _extract_content(self, concept_id: str, text: str) -> dict:
        prompt = (
            f"Extract animation content for '{concept_id}'. "
            "Return ONLY JSON, no markdown:\n"
            '{"title":"Short title (max 4 words)",'
            '"definition":"One sentence definition",'
            '"key_points":["point1","point2","point3","point4"],'
            '"formula":"Main formula or empty string",'
            '"fun_fact":"One surprising fact about this concept"}'
        )
        try:
            resp = self.llm.invoke(prompt)
            raw = resp.content.strip().strip("```json").strip("```").strip()
            data = json.loads(repair_json(raw))
            data.setdefault("title", concept_id)
            data.setdefault("definition", f"{concept_id} is a key concept.")
            data.setdefault("key_points", [
                "Understand the basics",
                "Apply the theory",
                "Practice with examples",
                "Master the concept",
            ])
            data.setdefault("formula", "")
            data.setdefault("fun_fact", f"{concept_id} is used across many industries.")
            return data
        except Exception:
            return {
                "title": concept_id,
                "definition": f"{concept_id} is an important concept.",
                "key_points": [
                    "Core theory",
                    "Practical usage",
                    "Real examples",
                    "Key takeaways",
                ],
                "formula": "",
                "fun_fact": f"Mastering {concept_id} opens many doors.",
            }

    def _build_html(self, concept_id: str, c: dict) -> str:
        points_js = json.dumps(c["key_points"])
        has_formula = bool(c.get("formula", "").strip())

        return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<style>
*{{margin:0;padding:0;box-sizing:border-box;}}
body{{background:#f8f9ff;font-family:'Inter',system-ui,sans-serif;overflow:hidden;}}
canvas{{display:block;margin:0 auto;}}
#controls{{text-align:center;padding:8px;}}
button{{
  background:#4f46e5;color:white;border:none;
  padding:8px 20px;border-radius:20px;cursor:pointer;
  font-size:13px;margin:0 4px;transition:background 0.2s;
}}
button:hover{{background:#4338ca;}}
#phase-label{{
  font-size:13px;color:#6b7280;margin-bottom:4px;
  font-family:'Inter',system-ui,sans-serif;text-align:center;padding:6px 0;
}}
</style>
</head>
<body>
<div id="phase-label">Click Play to start</div>
<canvas id="c"></canvas>
<div id="controls">
  <button onclick="prev()">&#9664; Prev</button>
  <button onclick="togglePlay()" id="playbtn">&#9654; Play</button>
  <button onclick="next()">Next &#9654;</button>
</div>
<script>
const canvas = document.getElementById('c');
const ctx = canvas.getContext('2d');
const W = 640, H = 340;
canvas.width = W; canvas.height = H;

const CONCEPT   = {json.dumps(concept_id)};
const TITLE     = {json.dumps(c["title"])};
const DEFINITION= {json.dumps(c["definition"])};
const KEY_POINTS= {points_js};
const FUN_FACT  = {json.dumps(c["fun_fact"])};
const FORMULA   = {json.dumps(c.get("formula", ""))};
const HAS_FORMULA = {json.dumps(has_formula)};

const SLIDES = [
  {{type:'title'}},
  {{type:'definition'}},
  ...(HAS_FORMULA ? [{{type:'formula'}}] : []),
  {{type:'points'}},
  {{type:'funfact'}},
  {{type:'summary'}},
];

let current = 0, playing = false, timer = null, animT = 0;

function wrapText(ctx, text, x, y, maxW, lineH) {{
  const words = text.split(' ');
  let line = '', lines = [];
  for (const w of words) {{
    const test = line + w + ' ';
    if (ctx.measureText(test).width > maxW && line) {{
      lines.push(line.trim()); line = w + ' ';
    }} else {{ line = test; }}
  }}
  if (line.trim()) lines.push(line.trim());
  lines.forEach((l, i) => ctx.fillText(l, x, y + i * lineH));
  return lines.length;
}}

function drawSlide(slide, t) {{
  ctx.clearRect(0, 0, W, H);
  const alpha = Math.min(1, t * 2);
  ctx.globalAlpha = alpha;

  if (slide.type === 'title') {{
    const grd = ctx.createLinearGradient(0,0,W,H);
    grd.addColorStop(0,'#667eea'); grd.addColorStop(1,'#764ba2');
    ctx.fillStyle = grd; ctx.fillRect(0,0,W,H);
    [[80,80,60],[560,260,80],[320,300,40]].forEach(([cx,cy,r]) => {{
      ctx.globalAlpha = alpha * 0.12;
      ctx.beginPath(); ctx.arc(cx+Math.sin(t)*8,cy+Math.cos(t)*5,r,0,Math.PI*2);
      ctx.fillStyle='white'; ctx.fill();
    }});
    ctx.globalAlpha = alpha;
    ctx.fillStyle='white'; ctx.textAlign='center';
    ctx.font='bold 34px Inter,system-ui,sans-serif';
    ctx.fillText(TITLE, W/2, 140 + Math.sin(t*1.5)*3);
    ctx.font='15px Inter,system-ui,sans-serif';
    ctx.globalAlpha = alpha * 0.85;
    wrapText(ctx, DEFINITION, W/2, 188, 520, 26);
    ctx.globalAlpha = alpha * 0.55;
    ctx.font='12px Inter,system-ui,sans-serif';
    ctx.fillText('Click Next to continue →', W/2, 300);

  }} else if (slide.type === 'definition') {{
    ctx.fillStyle='#f0f4ff'; ctx.fillRect(0,0,W,H);
    ctx.beginPath(); ctx.arc(W/2, 100+Math.sin(t)*4, 48, 0, Math.PI*2);
    ctx.fillStyle='#e0e7ff'; ctx.fill();
    ctx.fillStyle='#4f46e5'; ctx.font='bold 30px sans-serif';
    ctx.textAlign='center'; ctx.fillText('📖', W/2, 112);
    ctx.fillStyle='#1e1b4b'; ctx.font='bold 18px Inter,system-ui,sans-serif';
    ctx.fillText('What is ' + CONCEPT + '?', W/2, 178);
    ctx.fillStyle='#4b5563'; ctx.font='14px Inter,system-ui,sans-serif';
    wrapText(ctx, DEFINITION, W/2, 210, 560, 28);

  }} else if (slide.type === 'formula') {{
    ctx.fillStyle='#fffbeb'; ctx.fillRect(0,0,W,H);
    ctx.fillStyle='#92400e'; ctx.font='bold 20px Inter,system-ui,sans-serif';
    ctx.textAlign='center'; ctx.fillText('Core Formula', W/2, 80);
    const pulse = 1 + Math.sin(t*2)*0.018;
    ctx.save(); ctx.translate(W/2,175); ctx.scale(pulse,pulse);
    ctx.fillStyle='white'; ctx.shadowColor='#f59e0b'; ctx.shadowBlur=18;
    ctx.fillRect(-200,-42,400,84); ctx.shadowBlur=0;
    ctx.strokeStyle='#f59e0b'; ctx.lineWidth=2; ctx.strokeRect(-200,-42,400,84);
    ctx.restore();
    ctx.fillStyle='#1f2937'; ctx.font='bold 18px monospace';
    ctx.fillText(FORMULA, W/2, 184);
    ctx.fillStyle='#9ca3af'; ctx.font='12px Inter,system-ui,sans-serif';
    ctx.fillText('Study this formula carefully', W/2, 258);

  }} else if (slide.type === 'points') {{
    ctx.fillStyle='#f0fdf4'; ctx.fillRect(0,0,W,H);
    ctx.fillStyle='#14532d'; ctx.font='bold 18px Inter,system-ui,sans-serif';
    ctx.textAlign='center'; ctx.fillText('Key Concepts', W/2, 42);
    KEY_POINTS.forEach((pt, i) => {{
      const y=66+i*62, delay=i*0.3;
      const a2=Math.max(0,Math.min(1,(t-delay)*3));
      ctx.globalAlpha = alpha * a2;
      const x = 50 + (1-a2)*25;
      ctx.fillStyle='white'; ctx.shadowColor='rgba(0,0,0,0.07)'; ctx.shadowBlur=8;
      ctx.fillRect(x, y, W-x-50, 50); ctx.shadowBlur=0;
      ctx.fillStyle='#4f46e5'; ctx.beginPath();
      ctx.arc(x+22,y+25,14,0,Math.PI*2); ctx.fill();
      ctx.fillStyle='white'; ctx.font='bold 12px Inter,system-ui,sans-serif';
      ctx.textAlign='center'; ctx.fillText(i+1, x+22, y+30);
      ctx.fillStyle='#1f2937'; ctx.font='13px Inter,system-ui,sans-serif';
      ctx.textAlign='left'; ctx.fillText(pt, x+44, y+30);
    }});
    ctx.globalAlpha = alpha;

  }} else if (slide.type === 'funfact') {{
    const grd2=ctx.createLinearGradient(0,0,W,H);
    grd2.addColorStop(0,'#fdf4ff'); grd2.addColorStop(1,'#fce7f3');
    ctx.fillStyle=grd2; ctx.fillRect(0,0,W,H);
    [[80,60],[560,80],[100,280],[540,260],[320,50]].forEach(([sx,sy],i) => {{
      ctx.fillStyle='#a855f7';
      ctx.globalAlpha=alpha*(0.4+0.3*Math.sin(t*2+i));
      ctx.font='18px sans-serif'; ctx.textAlign='center'; ctx.fillText('✦',sx,sy);
    }});
    ctx.globalAlpha=alpha;
    ctx.fillStyle='#6b21a8'; ctx.font='bold 20px Inter,system-ui,sans-serif';
    ctx.textAlign='center'; ctx.fillText('✦ Did You Know?', W/2, 78);
    ctx.fillStyle='#581c87'; ctx.font='14px Inter,system-ui,sans-serif';
    wrapText(ctx, FUN_FACT, W/2, 125, 540, 28);

  }} else if (slide.type === 'summary') {{
    const grd3=ctx.createLinearGradient(0,0,W,H);
    grd3.addColorStop(0,'#1e1b4b'); grd3.addColorStop(1,'#312e81');
    ctx.fillStyle=grd3; ctx.fillRect(0,0,W,H);
    ctx.fillStyle='#c7d2fe'; ctx.font='bold 21px Inter,system-ui,sans-serif';
    ctx.textAlign='center';
    ctx.fillText("You've learned: "+CONCEPT, W/2, 68);
    ctx.font='26px sans-serif'; ctx.fillText('★★★★★', W/2, 122);
    ctx.fillStyle='#a5b4fc'; ctx.font='14px Inter,system-ui,sans-serif';
    wrapText(ctx,'You now understand the theory, examples,',W/2,162,520,26);
    wrapText(ctx,'and real-world applications of '+CONCEPT+'.',W/2,192,520,26);
    ctx.fillStyle='#6ee7b7'; ctx.font='bold 15px Inter,system-ui,sans-serif';
    ctx.fillText('Ready for the test? 🚀', W/2, 278);
  }}

  ctx.globalAlpha = 1;
  SLIDES.forEach((_,i) => {{
    ctx.beginPath();
    ctx.arc(W/2-(SLIDES.length-1)*12+i*24, H-14, 5, 0, Math.PI*2);
    ctx.fillStyle = i===current ? '#4f46e5' : '#d1d5db';
    ctx.fill();
  }});
  document.getElementById('phase-label').textContent =
    'Slide '+(current+1)+' of '+SLIDES.length+': '+SLIDES[current].type;
}}

function animate() {{
  animT += 0.016;
  drawSlide(SLIDES[current], animT);
  requestAnimationFrame(animate);
}}

function goTo(idx) {{
  current = Math.max(0, Math.min(SLIDES.length-1, idx));
  animT = 0;
}}
function next() {{ goTo(current+1); }}
function prev() {{ goTo(current-1); }}
function togglePlay() {{
  playing = !playing;
  document.getElementById('playbtn').textContent = playing ? '⏸ Pause' : '▶ Play';
  if (playing) {{
    timer = setInterval(() => {{
      if (current < SLIDES.length-1) {{ next(); }}
      else {{
        playing=false; clearInterval(timer);
        document.getElementById('playbtn').textContent='▶ Play';
      }}
    }}, 4000);
  }} else {{ clearInterval(timer); }}
}}

animate();
</script>
</body>
</html>"""
