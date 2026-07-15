import { useEffect, useRef, useState } from "react";
import {
  type ClipIdea,
  type CornerPosition,
  type ProcessedClip,
  type RenderOptions,
  type SourceKind,
  type TranscriptData,
  type UploadResult,
  downloadUrl,
  downloadYoutube,
  downloadZip,
  previewUrl,
  processClips,
  selectClips,
  transcribe,
  uploadFile,
} from "./api";
import { ProgressView, type Stage } from "./ProgressView";

const defaultOptions: RenderOptions = {
  shorts_format: true,
  burn_subtitles: true,
  normalize_audio: true,
  visual_cleanup: false,
  cleanup_position: "top_left",
  add_music: false,
  music_volume: 0.12,
  copyright_safe: false,
  mirror: false,
  add_logo: false,
};

const ANALYZE_STAGES: Stage[] = [
  { id: "import", label: "Import source", hint: "Reading your media" },
  { id: "transcribe", label: "Transcribe audio", hint: "Word-level timing" },
  { id: "analyze", label: "Find viral clips", hint: "Rank best moments" },
];
const ANALYZE_CEIL = [22, 58, 96];

const RENDER_STAGES: Stage[] = [
  { id: "prepare", label: "Prepare timeline", hint: "Lock in/out points" },
  { id: "cut", label: "Cut clips", hint: "Frame-accurate trims" },
  { id: "style", label: "Apply edits", hint: "Format, logo, captions, music" },
  { id: "finalize", label: "Finalize", hint: "Encode final MP4s" },
];
const RENDER_CEIL = [16, 46, 82, 97];

type Pipeline = { kind: "analyze" | "render"; activeIndex: number };

function formatDuration(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds <= 0) return "0:00";
  const total = Math.round(seconds);
  const minutes = Math.floor(total / 60);
  const secs = total % 60;
  return `${minutes}:${secs.toString().padStart(2, "0")}`;
}

function messagesFor(
  kind: "analyze" | "render",
  index: number,
  options: RenderOptions,
): string[] {
  if (kind === "analyze") {
    return [
      ["Reading your media…", "Extracting the audio track…", "Preparing the timeline…"],
      ["Listening to every word…", "Aligning word-level timing…", "Building the transcript…"],
      [
        "Scanning for hooks and payoffs…",
        "Ranking the most shareable moments…",
        "Writing titles, captions and hashtags…",
      ],
    ][index];
  }

  if (index === 0) return ["Preparing your selected clips…", "Locking your in and out points…"];
  if (index === 1) return ["Cutting frame-accurate clips…", "Trimming to the best moments…"];
  if (index === 2) {
    const steps: string[] = [];
    if (options.copyright_safe || options.mirror) steps.push("Applying copyright-safe edits…");
    if (options.shorts_format) steps.push("Reframing to vertical 9:16…");
    if (options.visual_cleanup) steps.push("Masking the original corner logo…");
    if (options.add_logo) steps.push("Placing your logo on top…");
    if (options.burn_subtitles) steps.push("Burning animated captions…");
    if (options.add_music) steps.push("Mixing in background music…");
    return steps.length ? steps : ["Applying your edits…"];
  }
  const finals: string[] = [];
  if (options.normalize_audio) finals.push("Normalizing loudness…");
  finals.push("Encoding final MP4s…", "Almost there…");
  return finals;
}

export default function App() {
  const [videoFile, setVideoFile] = useState<File | null>(null);
  const [musicFile, setMusicFile] = useState<File | null>(null);
  const [logoFile, setLogoFile] = useState<File | null>(null);
  const [youtubeUrl, setYoutubeUrl] = useState("");
  const [source, setSource] = useState<UploadResult | null>(null);
  const [transcriptData, setTranscriptData] = useState<TranscriptData | null>(null);
  const [clips, setClips] = useState<ClipIdea[]>([]);
  const [processed, setProcessed] = useState<ProcessedClip[]>([]);

  const [numClips, setNumClips] = useState(5);
  const [minLength, setMinLength] = useState(20);
  const [maxLength, setMaxLength] = useState(150);
  const [options, setOptions] = useState<RenderOptions>(defaultOptions);

  const [pipeline, setPipeline] = useState<Pipeline | null>(null);
  const [progress, setProgress] = useState(0);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  const targetRef = useRef(0);
  const busy = pipeline !== null;

  useEffect(() => {
    if (!busy) return;
    const id = window.setInterval(() => {
      setProgress((current) => {
        const target = targetRef.current;
        if (current >= target) return current;
        return current + Math.max(0.35, (target - current) * 0.05);
      });
    }, 90);
    return () => window.clearInterval(id);
  }, [busy]);

  useEffect(() => {
    if (!pipeline) {
      setMessage("");
      return;
    }
    const pool = messagesFor(pipeline.kind, pipeline.activeIndex, options);
    let index = 0;
    setMessage(pool[0]);
    const id = window.setInterval(() => {
      index = (index + 1) % pool.length;
      setMessage(pool[index]);
    }, 2200);
    return () => window.clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pipeline?.kind, pipeline?.activeIndex]);

  function startPipeline(kind: "analyze" | "render") {
    setError("");
    setProgress(0);
    targetRef.current = (kind === "analyze" ? ANALYZE_CEIL : RENDER_CEIL)[0];
    setPipeline({ kind, activeIndex: 0 });
  }

  function setStage(kind: "analyze" | "render", index: number) {
    targetRef.current = (kind === "analyze" ? ANALYZE_CEIL : RENDER_CEIL)[index];
    setPipeline({ kind, activeIndex: index });
  }

  function finishPipeline() {
    targetRef.current = 100;
    setProgress(100);
    window.setTimeout(() => setPipeline(null), 500);
  }

  function failPipeline(err: unknown, fallback: string) {
    setPipeline(null);
    setProgress(0);
    setError(err instanceof Error ? err.message : fallback);
  }

  function reset() {
    setVideoFile(null);
    setMusicFile(null);
    setLogoFile(null);
    setYoutubeUrl("");
    setSource(null);
    setTranscriptData(null);
    setClips([]);
    setProcessed([]);
    setError("");
    setPipeline(null);
    setProgress(0);
  }

  async function prepareSource(kind: SourceKind): Promise<UploadResult> {
    if (kind === "upload") {
      if (!videoFile) throw new Error("Choose a video file first.");
      const uploaded = await uploadFile(videoFile);
      const result = { ...uploaded, source: "upload" as const };
      setSource(result);
      return result;
    }
    if (!youtubeUrl.trim()) throw new Error("Paste a YouTube URL first.");
    const downloaded = await downloadYoutube(youtubeUrl.trim());
    setSource(downloaded);
    return downloaded;
  }

  async function createIdeas(kind: SourceKind) {
    setClips([]);
    setProcessed([]);
    setTranscriptData(null);
    startPipeline("analyze");
    try {
      const currentSource = await prepareSource(kind);
      setStage("analyze", 1);
      const result = await transcribe(currentSource.job_id, currentSource.file_path);
      setTranscriptData(result.transcript_data);
      setStage("analyze", 2);
      const ideas = await selectClips({
        jobId: currentSource.job_id,
        transcriptData: result.transcript_data,
        duration: currentSource.duration,
        numClips,
        minLength,
        maxLength,
      });
      setClips(ideas.clips.map((clip) => ({ ...clip, include: true })));
      finishPipeline();
    } catch (err) {
      failPipeline(err, "Something went wrong.");
    }
  }

  async function regenerate() {
    if (!source || !transcriptData) return;
    setProcessed([]);
    startPipeline("analyze");
    setStage("analyze", 2);
    try {
      const ideas = await selectClips({
        jobId: source.job_id,
        transcriptData,
        duration: source.duration,
        numClips,
        minLength,
        maxLength,
      });
      setClips(ideas.clips.map((clip) => ({ ...clip, include: true })));
      finishPipeline();
    } catch (err) {
      failPipeline(err, "Could not regenerate clips.");
    }
  }

  async function renderClips(polished: boolean) {
    if (!source || !transcriptData) {
      setError("Create clip ideas before rendering.");
      return;
    }
    if (clips.every((clip) => !(clip.include ?? true))) {
      setError("Select at least one clip to render.");
      return;
    }

    startPipeline("render");
    const timer = window.setInterval(() => {
      setPipeline((current) => {
        if (!current) return current;
        const next = Math.min(RENDER_STAGES.length - 1, current.activeIndex + 1);
        targetRef.current = RENDER_CEIL[next];
        return { ...current, activeIndex: next };
      });
    }, 3400);

    try {
      let musicPath: string | null = null;
      let logoPath: string | null = null;
      if (polished && options.add_music && musicFile) {
        musicPath = (await uploadFile(musicFile)).file_path;
      }
      if (polished && options.add_logo && logoFile) {
        logoPath = (await uploadFile(logoFile)).file_path;
      }

      const renderOptions: RenderOptions = polished
        ? {
            ...options,
            music_path: musicPath,
            add_music: options.add_music && Boolean(musicPath),
            logo_path: logoPath,
            add_logo: options.add_logo && Boolean(logoPath),
          }
        : {
            ...defaultOptions,
            shorts_format: false,
            burn_subtitles: false,
            normalize_audio: false,
            visual_cleanup: false,
            add_music: false,
            add_logo: false,
            copyright_safe: false,
            mirror: false,
            music_path: null,
            logo_path: null,
          };

      const result = await processClips({
        jobId: source.job_id,
        filePath: source.file_path,
        clips,
        transcriptData,
        options: renderOptions,
      });
      window.clearInterval(timer);
      setProcessed(result.processed_clips);
      finishPipeline();
    } catch (err) {
      window.clearInterval(timer);
      failPipeline(err, "Rendering failed.");
    }
  }

  async function handleZip() {
    if (!source || processed.length === 0) return;
    try {
      const blob = await downloadZip(source.job_id, processed.map((clip) => clip.output_path));
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `${source.job_id}_clips.zip`;
      link.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      setError(err instanceof Error ? err.message : "ZIP download failed.");
    }
  }

  function updateClip(index: number, patch: Partial<ClipIdea>) {
    setClips((items) => items.map((clip, i) => (i === index ? { ...clip, ...patch } : clip)));
  }

  function setOption<K extends keyof RenderOptions>(key: K, value: RenderOptions[K]) {
    setOptions((current) => ({ ...current, [key]: value }));
  }

  const selectedCount = clips.filter((clip) => clip.include ?? true).length;
  const stages = pipeline?.kind === "render" ? RENDER_STAGES : ANALYZE_STAGES;

  return (
    <main className="app">
      {/* LEFT: Source */}
      <aside className="rail rail-left">
        <div className="brand">
          <span className="logo">VC</span>
          <div>
            <h1>VideoClipper AI</h1>
            <p>Long video → viral clips</p>
          </div>
        </div>

        <section className="rail-section">
          <h2>Source</h2>
          <label className="file-button">
            <input
              type="file"
              accept="video/mp4,video/quicktime,video/x-matroska,video/x-msvideo"
              disabled={busy}
              onChange={(event) => setVideoFile(event.target.files?.[0] ?? null)}
            />
            <span>{videoFile ? videoFile.name : "Choose a video file"}</span>
          </label>
          <button className="primary block" disabled={!videoFile || busy} onClick={() => createIdeas("upload")}>
            Analyze upload
          </button>

          <div className="divider">or</div>

          <label className="field">
            <span>YouTube URL</span>
            <input
              value={youtubeUrl}
              disabled={busy}
              placeholder="Paste a link"
              onChange={(event) => setYoutubeUrl(event.target.value)}
            />
          </label>
          <button className="block" disabled={!youtubeUrl.trim() || busy} onClick={() => createIdeas("youtube")}>
            Analyze link
          </button>
        </section>

        {source && (
          <section className="rail-section">
            <h2>Loaded source</h2>
            <div className="source-card">
              <video src={previewUrl(source.filename)} muted preload="metadata" />
              <div>
                <b>{source.title ?? source.filename}</b>
                <small>{source.source === "youtube" ? "YouTube" : "Upload"} · {formatDuration(source.duration)}</small>
              </div>
            </div>
          </section>
        )}

        <button className="muted block push-bottom" disabled={busy} onClick={reset}>
          Reset project
        </button>
      </aside>

      {/* CENTER: Workspace */}
      <section className="workspace">
        <header className="topbar">
          <div>
            <h2>Studio</h2>
            <p>
              {busy
                ? "Working on your video…"
                : clips.length > 0
                  ? "Review your clip ideas, then render."
                  : "Choose a source on the left and controls on the right."}
            </p>
          </div>
          <div className="status">
            <span className={busy ? "chip working" : "chip"}>{busy ? "Working" : "Ready"}</span>
            {clips.length > 0 && <b>{selectedCount}/{clips.length}</b>}
          </div>
        </header>

        {error && <div className="alert">{error}</div>}

        {busy && (
          <ProgressView
            title={pipeline?.kind === "render" ? "Rendering your clips" : "Analyzing your video"}
            stages={stages}
            activeIndex={pipeline?.activeIndex ?? 0}
            progress={progress}
            message={message}
            previewSrc={source?.filename ? previewUrl(source.filename) : undefined}
          />
        )}

        {!busy && processed.length > 0 && (
          <section className="panel">
            <div className="panel-head">
              <h2>Finished clips</h2>
              <button className="primary" onClick={handleZip}>Download all (ZIP)</button>
            </div>
            <div className="download-grid">
              {processed.map((clip) => {
                const url = downloadUrl(clip.filename);
                const caption = [clip.title, clip.description, clip.hashtags?.join(" ")]
                  .filter(Boolean)
                  .join("\n\n");
                return (
                  <article className="download-card" key={clip.filename}>
                    <div className="clip-player">
                      <video controls src={url} preload="metadata" />
                    </div>
                    <div className="download-meta">
                      <h3>{clip.title}</h3>
                      <div className="score-row">
                        <span className="score">Viral <b>{clip.virality_score}</b></span>
                        <span className="score">Hook <b>{clip.hook_score}</b></span>
                        <span className="score">Content <b>{clip.content_score}</b></span>
                      </div>
                      <textarea value={caption} readOnly />
                      <a className="primary" href={url} download>Download MP4</a>
                    </div>
                  </article>
                );
              })}
            </div>
          </section>
        )}

        {!busy && clips.length > 0 && (
          <section className="panel">
            <div className="panel-head">
              <h2>Clip ideas</h2>
              <div className="actions">
                <button onClick={regenerate}>Regenerate</button>
                <button onClick={() => renderClips(false)}>Fast cuts</button>
                <button className="primary" disabled={selectedCount === 0} onClick={() => renderClips(true)}>
                  Render polished
                </button>
              </div>
            </div>

            <div className="clip-table">
              {clips.map((clip, index) => (
                <details className="clip-row" key={`${clip.clip_number}-${clip.start_time}`}>
                  <summary>
                    <input
                      type="checkbox"
                      checked={clip.include ?? true}
                      onClick={(event) => event.stopPropagation()}
                      onChange={(event) => updateClip(index, { include: event.target.checked })}
                    />
                    <span className="clip-title">#{clip.clip_number} · {clip.title}</span>
                    <span className="clip-time">{formatDuration(clip.start_time)}–{formatDuration(clip.end_time)}</span>
                    <span className="score compact">V<b>{clip.virality_score}</b></span>
                    <span className="score compact">H<b>{clip.hook_score}</b></span>
                    <span className="score compact">C<b>{clip.content_score}</b></span>
                    <span className="chevron">⌄</span>
                  </summary>

                  <div className="clip-detail">
                    <div className="clip-detail-grid">
                      {source?.filename && (
                        <div className="clip-preview">
                          <video
                            controls
                            preload="metadata"
                            src={`${previewUrl(source.filename)}#t=${Math.floor(clip.start_time)}`}
                          />
                          <small>Source preview from {formatDuration(clip.start_time)}</small>
                        </div>
                      )}
                      <div className="clip-info">
                        {clip.reason && <p className="reason">{clip.reason}</p>}
                        <div className="time-grid">
                          <label>
                            Start (s)
                            <input type="number" min="0" step="0.5" value={clip.start_time}
                              onChange={(event) => updateClip(index, { start_time: Number(event.target.value) })} />
                          </label>
                          <label>
                            End (s)
                            <input type="number" min="0" step="0.5" value={clip.end_time}
                              onChange={(event) => updateClip(index, { end_time: Number(event.target.value) })} />
                          </label>
                        </div>
                        {clip.description && <p className="desc">{clip.description}</p>}
                        {clip.hashtags?.length > 0 && (
                          <div className="hashtags">
                            {clip.hashtags.map((tag) => <span key={tag}>{tag}</span>)}
                          </div>
                        )}
                      </div>
                    </div>
                  </div>
                </details>
              ))}
            </div>
          </section>
        )}

        {!busy && clips.length === 0 && processed.length === 0 && (
          <section className="empty">
            <div className="empty-badge">🎬</div>
            <h2>Turn one long video into ready-to-post clips</h2>
            <p>
              Load a video or YouTube link on the left, set your clip and edit
              controls on the right, then analyze. You will see live progress,
              review ranked clip ideas, and download polished vertical clips with
              captions, your logo, and background music.
            </p>
            <ol className="empty-steps">
              <li><b>1</b> Add a source</li>
              <li><b>2</b> Set controls</li>
              <li><b>3</b> Analyze</li>
              <li><b>4</b> Render &amp; download</li>
            </ol>
          </section>
        )}
      </section>

      {/* RIGHT: Controls */}
      <aside className="rail rail-right">
        <section className="rail-section">
          <h2>Clip controls</h2>
          <label className="range">
            <span>Number of clips <b>{numClips}</b></span>
            <input type="range" min="2" max="8" value={numClips} disabled={busy}
              onChange={(event) => setNumClips(Number(event.target.value))} />
          </label>
          <label className="range">
            <span>Minimum length <b>{minLength}s</b></span>
            <input type="range" min="10" max="90" step="5" value={minLength} disabled={busy}
              onChange={(event) => setMinLength(Number(event.target.value))} />
          </label>
          <label className="range">
            <span>Maximum length <b>{maxLength}s</b></span>
            <input type="range" min="60" max="240" step="10" value={maxLength} disabled={busy}
              onChange={(event) => setMaxLength(Number(event.target.value))} />
          </label>
        </section>

        <section className="rail-section">
          <h2>Format &amp; captions</h2>
          <label className="toggle">
            <span>Vertical 9:16</span>
            <input type="checkbox" checked={options.shorts_format} disabled={busy}
              onChange={(event) => setOption("shorts_format", event.target.checked)} />
          </label>
          <label className="toggle">
            <span>Animated captions</span>
            <input type="checkbox" checked={options.burn_subtitles} disabled={busy}
              onChange={(event) => setOption("burn_subtitles", event.target.checked)} />
          </label>
          <label className="toggle">
            <span>Normalize audio</span>
            <input type="checkbox" checked={options.normalize_audio} disabled={busy}
              onChange={(event) => setOption("normalize_audio", event.target.checked)} />
          </label>
        </section>

        <section className="rail-section">
          <h2>Branding</h2>
          <label className="toggle">
            <span>Mask original logo</span>
            <input type="checkbox" checked={options.visual_cleanup} disabled={busy}
              onChange={(event) => setOption("visual_cleanup", event.target.checked)} />
          </label>
          <label className="toggle">
            <span>Overlay my logo</span>
            <input type="checkbox" checked={options.add_logo} disabled={busy}
              onChange={(event) => setOption("add_logo", event.target.checked)} />
          </label>
          {options.add_logo && (
            <label className="file-button small">
              <input type="file" accept="image/png,image/jpeg,image/webp" disabled={busy}
                onChange={(event) => setLogoFile(event.target.files?.[0] ?? null)} />
              <span>{logoFile ? logoFile.name : "Choose logo (PNG)"}</span>
            </label>
          )}
          {(options.visual_cleanup || options.add_logo) && (
            <label className="field">
              <span>Corner</span>
              <select value={options.cleanup_position} disabled={busy}
                onChange={(event) => setOption("cleanup_position", event.target.value as CornerPosition)}>
                <option value="top_left">Top left</option>
                <option value="top_right">Top right</option>
                <option value="bottom_left">Bottom left</option>
                <option value="bottom_right">Bottom right</option>
              </select>
            </label>
          )}
          {options.add_logo && options.visual_cleanup === false && (
            <p className="hint">Tip: also enable “Mask original logo” to hide the channel’s logo behind yours.</p>
          )}
        </section>

        <section className="rail-section">
          <h2>Music</h2>
          <label className="toggle">
            <span>Background music</span>
            <input type="checkbox" checked={options.add_music} disabled={busy}
              onChange={(event) => setOption("add_music", event.target.checked)} />
          </label>
          {options.add_music && (
            <>
              <label className="file-button small">
                <input type="file" accept="audio/mpeg,audio/wav,audio/x-m4a,audio/mp4" disabled={busy}
                  onChange={(event) => setMusicFile(event.target.files?.[0] ?? null)} />
                <span>{musicFile ? musicFile.name : "Choose music"}</span>
              </label>
              <label className="range">
                <span>Music volume <b>{Math.round(options.music_volume * 100)}%</b></span>
                <input type="range" min="0.02" max="0.5" step="0.01" value={options.music_volume} disabled={busy}
                  onChange={(event) => setOption("music_volume", Number(event.target.value))} />
              </label>
            </>
          )}
        </section>

        <section className="rail-section">
          <h2>Copyright safety</h2>
          <label className="toggle">
            <span>Reduce copyright matching</span>
            <input type="checkbox" checked={options.copyright_safe} disabled={busy}
              onChange={(event) => setOption("copyright_safe", event.target.checked)} />
          </label>
          <label className="toggle">
            <span>Mirror flip</span>
            <input type="checkbox" checked={options.mirror} disabled={busy}
              onChange={(event) => setOption("mirror", event.target.checked)} />
          </label>
          <p className="hint">
            Subtle zoom, color grade and optional mirror reduce content-ID matches.
            This does not grant rights to reuse content you do not own.
          </p>
        </section>
      </aside>
    </main>
  );
}
