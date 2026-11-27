import { ImageOff, Maximize2, Minimize2, ZoomIn, ZoomOut } from 'lucide-react';
import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import type { Region } from '../lib/types';
import { Skeleton } from './primitives';

/**
 * The rendered page from ai_parse_document, with the cited evidence drawn over it. Regions are in
 * page-image pixels (as ai_extract's citations report them), so they scale with the image.
 */
export function DocumentViewer({
  docId,
  pageCount,
  enabled,
  selected,
  caption,
}: {
  docId: string;
  pageCount: number;
  enabled: boolean;
  selected: {
    label: string;
    regions: Region[];
    value: string | null;
    elsewhere?: boolean;
  } | null;
  caption?: string;
}) {
  const [page, setPage] = useState(0);
  const [zoom, setZoom] = useState(false);
  const [loaded, setLoaded] = useState<{ src: string; w: number; h: number } | null>(null);
  const [failed, setFailed] = useState<string | null>(null);
  const [prevSelected, setPrevSelected] = useState(selected);
  const [prevDoc, setPrevDoc] = useState(docId);
  const [lensOn, setLensOn] = useState(true);
  const [lensWidth, setLensWidth] = useState(0);
  const scrollRef = useRef<HTMLDivElement>(null);
  const paperRef = useRef<HTMLDivElement>(null);
  const lensBoxRef = useRef<HTMLDivElement>(null);

  // The lens fills the viewer's width; track it so the magnification is exact.
  useEffect(() => {
    const el = lensBoxRef.current;
    if (!el) return;
    const ro = new ResizeObserver(([entry]) => setLensWidth(Math.floor(entry.contentRect.width)));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // Follow a newly selected field to its page; start a new document on page one.
  if (docId !== prevDoc) {
    setPrevDoc(docId);
    setPage(0);
  }
  if (selected !== prevSelected) {
    setPrevSelected(selected);
    const target = selected?.regions[0]?.page;
    if (target != null && target !== page && target < pageCount) setPage(target);
  }

  const src = `/api/documents/${docId}/pages/${page}`;
  const size = loaded?.src === src ? loaded : null;
  const state: 'loading' | 'ready' | 'error' = failed === src ? 'error' : size ? 'ready' : 'loading';

  // Bring the selected evidence into view inside the scroll box.
  useLayoutEffect(() => {
    const region = selected?.regions.find((r) => r.page === page);
    const box = scrollRef.current;
    const paper = paperRef.current;
    if (!region || !box || !paper || !size) return;
    const scale = paper.clientWidth / size.w;
    const top = paper.offsetTop + region.y0 * scale - box.clientHeight / 3;
    const left = paper.offsetLeft + region.x0 * scale - box.clientWidth / 4;
    box.scrollTo({ top: Math.max(0, top), left: zoom ? Math.max(0, left) : 0, behavior: 'smooth' });
  }, [selected, page, size, zoom]);

  const onPage = (r: Region) => r.page === page;

  // A magnified crop of the actual page pixels around the cited region, so the printed text can be
  // read at a legible size beside the decision. Height is capped; width follows the viewer.
  const lensRegion = selected?.regions.find(onPage);
  const lens = (() => {
    if (!lensRegion || !size || !lensWidth) return null;
    const padX = 24;
    const padY = 10;
    const x0 = Math.max(0, lensRegion.x0 - padX);
    const y0 = Math.max(0, lensRegion.y0 - padY);
    const x1 = Math.min(size.w, lensRegion.x1 + padX);
    const y1 = Math.min(size.h, lensRegion.y1 + padY);
    // At least ~print size (the page image is rendered at about 200 dpi); a wide region scrolls
    // sideways inside the lens rather than shrinking below legibility.
    const scale = Math.max(0.9, Math.min(lensWidth / (x1 - x0), 200 / (y1 - y0), 2.4));
    return {
      width: Math.round((x1 - x0) * scale),
      height: Math.round((y1 - y0) * scale),
      bgSize: `${Math.round(size.w * scale)}px ${Math.round(size.h * scale)}px`,
      bgPos: `${Math.round(-x0 * scale)}px ${Math.round(-y0 * scale)}px`,
      mark: {
        left: Math.round((lensRegion.x0 - x0) * scale),
        top: Math.round((lensRegion.y0 - y0) * scale),
        width: Math.round((lensRegion.x1 - lensRegion.x0) * scale),
        height: Math.round((lensRegion.y1 - lensRegion.y0) * scale),
      },
    };
  })();

  return (
    <section className="document-view" aria-label="Source document">
      <div className="viewer-bar">
        <span>
          {docId} · page {page + 1} of {Math.max(pageCount, 1)}
        </span>
        <span className="pages">
          {pageCount > 1 &&
            Array.from({ length: pageCount }, (_, i) => (
              <button
                key={i}
                className="filter"
                aria-pressed={i === page}
                onClick={() => setPage(i)}
                aria-label={`Page ${i + 1}`}
              >
                {i + 1}
              </button>
            ))}
          {lensRegion && (
            <button
              className="button small ghost icon-button"
              onClick={() => setLensOn((v) => !v)}
              aria-label={lensOn ? 'Hide the magnified evidence' : 'Show the magnified evidence'}
              aria-pressed={lensOn}
              title={lensOn ? 'Whole page only' : 'Magnify the evidence'}
            >
              {lensOn ? <Minimize2 aria-hidden="true" /> : <Maximize2 aria-hidden="true" />}
            </button>
          )}
          <button
            className="button small ghost icon-button"
            onClick={() => setZoom((z) => !z)}
            aria-label={zoom ? 'Fit page to width' : 'Zoom in'}
            aria-pressed={zoom}
          >
            {zoom ? <ZoomOut aria-hidden="true" /> : <ZoomIn aria-hidden="true" />}
          </button>
        </span>
      </div>
      <div className="lens-box" ref={lensBoxRef}>
        {lens && lensOn && enabled && (
          <div className="lens-scroll">
            <div
              className="lens"
              role="img"
              aria-label={`${selected?.label ?? 'Evidence'} as printed on the page, magnified`}
              style={{
                width: lens.width,
                height: lens.height,
                backgroundImage: `url(${src})`,
                backgroundSize: lens.bgSize,
                backgroundPosition: lens.bgPos,
              }}
            >
              <span className="lens-mark" style={lens.mark} aria-hidden="true" />
            </div>
          </div>
        )}
      </div>
      <div className="viewer-scroll" ref={scrollRef}>
        {!enabled ? (
          <div className="viewer-empty">
            <ImageOff aria-hidden="true" />
            <p>
              Page images are not available in this deployment. The extracted fields and their cited text are still
              shown.
            </p>
          </div>
        ) : (
          <div className={`paper${zoom ? ' zoomed' : ''}`} ref={paperRef}>
            {state === 'loading' && (
              <div style={{ padding: 24, lineHeight: 1 }}>
                <Skeleton height={360} />
              </div>
            )}
            {state === 'error' ? (
              <div className="viewer-empty">
                <ImageOff aria-hidden="true" />
                <p>This page could not be loaded. You may not have access to the document volume.</p>
              </div>
            ) : (
              <img
                key={src}
                src={src}
                alt={`Page ${page + 1} of ${docId} as received`}
                style={state === 'ready' ? undefined : { position: 'absolute', opacity: 0 }}
                onLoad={(e) => setLoaded({ src, w: e.currentTarget.naturalWidth, h: e.currentTarget.naturalHeight })}
                onError={() => setFailed(src)}
              />
            )}
            {size && state === 'ready' && (
              <svg viewBox={`0 0 ${size.w} ${size.h}`} preserveAspectRatio="none" aria-hidden="true">
                {(selected?.regions ?? []).filter(onPage).map((r) => (
                  <rect
                    key={`s-${r.x0}-${r.y0}-${r.x1}-${r.y1}`}
                    className="evidence-box selected"
                    x={r.x0 - 6}
                    y={r.y0 - 6}
                    width={r.x1 - r.x0 + 12}
                    height={r.y1 - r.y0 + 12}
                  />
                ))}
              </svg>
            )}
          </div>
        )}
      </div>
      {(selected || caption) && (
        <div className="viewer-caption" aria-live="polite">
          {selected ? (
            <>
              <strong>{selected.label}</strong>
              {!selected.regions.length
                ? selected.value
                  ? ': no location was cited. Find it on the page before you confirm it.'
                  : ': not found on the document.'
                : selected.elsewhere
                  ? ' was found elsewhere on the document, not where the model cited. Find it before you confirm.'
                  : ' is highlighted on the page.'}
            </>
          ) : (
            caption
          )}
        </div>
      )}
    </section>
  );
}
