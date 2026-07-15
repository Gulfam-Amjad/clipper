export type Stage = {
  id: string;
  label: string;
  hint: string;
};

type ProgressViewProps = {
  title: string;
  stages: Stage[];
  activeIndex: number;
  progress: number;
  message: string;
  previewSrc?: string;
};

export function ProgressView({
  title,
  stages,
  activeIndex,
  progress,
  message,
  previewSrc,
}: ProgressViewProps) {
  const rounded = Math.min(100, Math.max(0, Math.round(progress)));

  return (
    <section className="progress-view">
      <div className="progress-visual">
        <div className="preview-frame">
          {previewSrc ? (
            <video src={previewSrc} muted autoPlay loop playsInline />
          ) : (
            <div className="preview-fallback" />
          )}
          <div className="scanline" />
          <div className="preview-grid" />
          <div className="equalizer">
            {Array.from({ length: 7 }).map((_, index) => (
              <span key={index} style={{ animationDelay: `${index * 0.11}s` }} />
            ))}
          </div>
        </div>
        <div className="progress-ring" data-value={rounded}>
          <svg viewBox="0 0 120 120">
            <circle className="ring-track" cx="60" cy="60" r="52" />
            <circle
              className="ring-fill"
              cx="60"
              cy="60"
              r="52"
              style={{ strokeDashoffset: 327 - (327 * rounded) / 100 }}
            />
          </svg>
          <div className="ring-label">
            <b>{rounded}%</b>
            <span>working</span>
          </div>
        </div>
      </div>

      <div className="progress-body">
        <h2>{title}</h2>
        <p className="progress-message">{message}</p>

        <div className="progress-bar">
          <span style={{ width: `${rounded}%` }} />
        </div>

        <ol className="stage-list">
          {stages.map((stage, index) => {
            const state =
              index < activeIndex ? "done" : index === activeIndex ? "active" : "pending";
            return (
              <li key={stage.id} className={`stage ${state}`}>
                <span className="stage-dot">
                  {state === "done" ? "✓" : index + 1}
                </span>
                <div>
                  <b>{stage.label}</b>
                  <small>{stage.hint}</small>
                </div>
              </li>
            );
          })}
        </ol>
      </div>
    </section>
  );
}
