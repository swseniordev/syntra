export function Brand({ inverse = false }: { inverse?: boolean }) {
  return (
    <div className={`brand-mark${inverse ? ' brand-mark--inverse' : ''}`} aria-label="Syntra">
      <img className="brand-symbol-image" src="/brand/symbol.png" alt="" />
      {inverse ? <img className="brand-word-image" src="/brand/word-light.png" alt="" /> : <span className="brand-word">Syntra</span>}
    </div>
  );
}
