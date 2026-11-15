// Lays the narration clips onto the recorded video at their cue times -> MP4 (H.264 + AAC).
//   node video/mix.mjs [out.mp4]      (needs ffmpeg on PATH)
import { execFileSync } from "node:child_process";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..", "video-output");
const out = resolve(process.argv[2] ?? join(root, "VeriPantry-demo.mp4"));
const find = (dir) => readdirSync(dir).flatMap((f) => {
  const p = join(dir, f);
  return statSync(p).isDirectory() ? find(p) : p.endsWith(".webm") ? [p] : [];
});
const video = find(join(root, "run"))[0];
const cues = JSON.parse(readFileSync(join(root, "cues.json"), "utf8"));
// The video starts a moment before the test body; shift voice by this much (ms).
const lead = Number(process.env.VOICE_LEAD_MS ?? 250);

const args = ["-y", "-i", video];
cues.forEach((c) => args.push("-i", join(root, "voice", `${c.id}.wav`)));
const parts = cues.map((c, i) => `[${i + 1}:a]adelay=${c.at + lead}:all=1[a${i}]`);
const mix = `${cues.map((_, i) => `[a${i}]`).join("")}amix=inputs=${cues.length}:normalize=0,volume=1.5,alimiter=limit=0.89:level=false,apad[aout]`;
args.push(
  "-filter_complex", [...parts, mix].join(";"),
  "-map", "0:v", "-map", "[aout]", "-shortest",
  "-c:v", "libx264", "-preset", "slow", "-crf", "20", "-pix_fmt", "yuv420p",
  "-c:a", "aac", "-b:a", "160k", "-ar", "44100", "-movflags", "+faststart", out,
);
execFileSync("ffmpeg", args, { stdio: ["ignore", "ignore", "inherit"] });
console.log(`Wrote ${out}`);
