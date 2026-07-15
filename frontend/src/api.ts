export const API_BASE = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

export type SourceKind = "upload" | "youtube";

export type UploadResult = {
  job_id: string;
  filename: string;
  duration: number;
  file_path: string;
  source?: SourceKind;
  source_url?: string;
  title?: string;
  uploader?: string;
  view_count?: number;
};

export type TranscriptData = {
  full_text: string;
  segments: Array<{ start: number; end: number; text: string }>;
  words: Array<{ word: string; start: number; end: number }>;
};

export type TranscribeResult = {
  transcript: string;
  segments: TranscriptData["segments"];
  words: TranscriptData["words"];
  transcript_data: TranscriptData;
};

export type ClipIdea = {
  clip_number: number;
  start_time: number;
  end_time: number;
  title: string;
  reason: string;
  description: string;
  hashtags: string[];
  virality_score: number;
  hook_score: number;
  content_score: number;
  include?: boolean;
};

export type ProcessedClip = ClipIdea & {
  output_path: string;
  filename: string;
};

export type CornerPosition = "top_left" | "top_right" | "bottom_left" | "bottom_right";

export type RenderOptions = {
  shorts_format: boolean;
  burn_subtitles: boolean;
  normalize_audio: boolean;
  visual_cleanup: boolean;
  cleanup_position: CornerPosition;
  add_music: boolean;
  music_volume: number;
  music_path?: string | null;
  copyright_safe: boolean;
  mirror: boolean;
  add_logo: boolean;
  logo_path?: string | null;
};

async function readError(response: Response): Promise<string> {
  const text = await response.text();
  try {
    const parsed = JSON.parse(text);
    return typeof parsed?.detail === "string" ? parsed.detail : text;
  } catch {
    return text || response.statusText;
  }
}

async function postJson<T>(endpoint: string, body: unknown): Promise<T> {
  const response = await fetch(`${API_BASE}${endpoint}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) throw new Error(await readError(response));
  return response.json() as Promise<T>;
}

export async function uploadFile(file: File): Promise<UploadResult> {
  const form = new FormData();
  form.append("file", file);
  const response = await fetch(`${API_BASE}/upload`, {
    method: "POST",
    body: form,
  });
  if (!response.ok) throw new Error(await readError(response));
  return response.json() as Promise<UploadResult>;
}

export function downloadYoutube(url: string): Promise<UploadResult> {
  return postJson<UploadResult>("/download-youtube", { url });
}

export function transcribe(jobId: string, filePath: string): Promise<TranscribeResult> {
  return postJson<TranscribeResult>("/transcribe", {
    job_id: jobId,
    file_path: filePath,
  });
}

export function selectClips(params: {
  jobId: string;
  transcriptData: TranscriptData;
  duration: number;
  numClips: number;
  minLength: number;
  maxLength: number;
}): Promise<{ clips: ClipIdea[] }> {
  return postJson<{ clips: ClipIdea[] }>("/select-clips", {
    job_id: params.jobId,
    transcript_data: params.transcriptData,
    video_duration: params.duration,
    num_clips: params.numClips,
    min_length: params.minLength,
    max_length: params.maxLength,
  });
}

export function processClips(params: {
  jobId: string;
  filePath: string;
  clips: ClipIdea[];
  transcriptData: TranscriptData;
  options: RenderOptions;
}): Promise<{ processed_clips: ProcessedClip[] }> {
  return postJson<{ processed_clips: ProcessedClip[] }>("/process-clips", {
    job_id: params.jobId,
    file_path: params.filePath,
    clips: params.clips,
    transcript_data: params.transcriptData,
    options: params.options,
  });
}

export async function downloadZip(jobId: string, clipPaths: string[]): Promise<Blob> {
  const response = await fetch(`${API_BASE}/download-zip`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ job_id: jobId, clip_paths: clipPaths }),
  });
  if (!response.ok) throw new Error(await readError(response));
  return response.blob();
}

export function previewUrl(filename: string): string {
  return `${API_BASE}/preview-upload/${filename}`;
}

export function downloadUrl(filename: string): string {
  return `${API_BASE}/download/${filename}`;
}
