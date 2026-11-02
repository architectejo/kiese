import React, { useState } from 'react';

// --- Types ---
export interface ChartDataPoint {
  label: string;
  value: number;
}

interface ChartProps {
  data: ChartDataPoint[];
  height?: number;
  color?: string;
  gradientId?: string;
}

// Helper to format currency
const formatFC = (num: number) => {
  return new Intl.NumberFormat('fr-CD', { style: 'currency', currency: 'CDF', maximumFractionDigits: 0 })
    .format(num)
    .replace('CDF', 'FC');
};

// ─── 1. TrendChart (Interactive SVG Area Chart) ───────────────────
export const TrendChart: React.FC<ChartProps> = ({
  data,
  height = 200,
  color = 'hsl(var(--accent-color))',
  gradientId = 'trendGradient'
}) => {
  const [activeIdx, setActiveIdx] = useState<number | null>(null);

  if (!data || data.length === 0) return null;

  // Duplicate single-point data so division (length-1) is never 0
  const plotData = data.length === 1 ? [data[0], data[0]] : data;

  const width = 500;
  const padding = 40;
  const chartWidth = width - padding * 2;
  const chartHeight = height - padding * 2;

  const maxVal = Math.max(...plotData.map(d => d.value)) * 1.15 || 100;
  const minVal = 0;

  // Generate points
  const points = plotData.map((d, index) => {
    const x = padding + (index / (plotData.length - 1)) * chartWidth;
    const y = padding + chartHeight - ((d.value - minVal) / (maxVal - minVal)) * chartHeight;
    return { x, y, ...d };
  });

  // Create path command
  const pathD = points.reduce((acc, p, i) => {
    return i === 0 ? `M ${p.x} ${p.y}` : `${acc} L ${p.x} ${p.y}`;
  }, '');

  // Area path (closed at the bottom)
  const areaD = points.length > 0 
    ? `${pathD} L ${points[points.length - 1].x} ${height - padding} L ${points[0].x} ${height - padding} Z`
    : '';

  return (
    <div style={{ position: 'relative', width: '100%' }}>
      <svg viewBox={`0 0 ${width} ${height}`} style={{ width: '100%', height: 'auto', overflow: 'visible' }}>
        <defs>
          {/* Glowing area gradient */}
          <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity="0.4" />
            <stop offset="100%" stopColor={color} stopOpacity="0.0" />
          </linearGradient>
        </defs>

        {/* Horizontal grid lines */}
        {[0, 0.25, 0.5, 0.75, 1].map((ratio, idx) => {
          const y = padding + ratio * chartHeight;
          const val = maxVal - ratio * (maxVal - minVal);
          return (
            <g key={idx} opacity="0.15">
              <line 
                x1={padding} 
                y1={y} 
                x2={width - padding} 
                y2={y} 
                stroke="currentColor" 
                strokeDasharray="4"
              />
              <text 
                x={padding - 8} 
                y={y + 4} 
                textAnchor="end" 
                fontSize="10" 
                fill="currentColor"
                fontWeight="600"
              >
                {val > 1000 ? `${(val / 1000).toFixed(0)}k` : val.toFixed(0)}
              </text>
            </g>
          );
        })}

        {/* Shaded Area */}
        <path d={areaD} fill={`url(#${gradientId})`} />

        {/* Main Line */}
        <path 
          d={pathD} 
          fill="none" 
          stroke={color} 
          strokeWidth="3" 
          strokeLinecap="round"
          strokeLinejoin="round"
          style={{ transition: 'stroke 0.3s ease' }}
        />

        {/* Interactivity Zones & Data Points */}
        {points.map((p, idx) => (
          <g key={idx}>
            {/* Glow dot on hover */}
            {activeIdx === idx && (
              <circle 
                cx={p.x} 
                cy={p.y} 
                r="10" 
                fill={color} 
                opacity="0.25" 
                style={{ transition: 'all 0.1s ease' }}
              />
            )}
            
            {/* Real dot */}
            <circle 
              cx={p.x} 
              cy={p.y} 
              r={activeIdx === idx ? "6" : "4"} 
              fill={activeIdx === idx ? "#070c1c" : color}
              stroke={color}
              strokeWidth="2"
              style={{ transition: 'all 0.15s ease', cursor: 'pointer' }}
            />

            {/* Invisible large hover catcher */}
            <rect
              x={p.x - chartWidth / (plotData.length * 2)}
              y={padding}
              width={chartWidth / (plotData.length - 1)}
              height={chartHeight}
              fill="transparent"
              style={{ cursor: 'pointer' }}
              onMouseEnter={() => setActiveIdx(idx)}
              onMouseLeave={() => setActiveIdx(null)}
            />
          </g>
        ))}

        {/* X Axis Labels */}
        {points.map((p, idx) => {
          // Only render first, middle, last to avoid crowding; skip duplicate for single-data-point
          if (data.length === 1 && idx === 1) return null;
          if (idx === 0 || idx === Math.floor(points.length / 2) || idx === points.length - 1) {
            return (
              <text
                key={idx}
                x={p.x}
                y={height - padding + 20}
                textAnchor="middle"
                fontSize="10"
                fill="currentColor"
                opacity="0.5"
                fontWeight="700"
              >
                {p.label}
              </text>
            );
          }
          return null;
        })}
      </svg>

      {/* Floating Interactive Tooltip */}
      {activeIdx !== null && (
        <div style={{
          position: 'absolute',
          top: '8px',
          left: '50%',
          transform: 'translateX(-50%)',
          backgroundColor: 'var(--glass-bg)',
          backdropFilter: 'var(--glass-filter)',
          border: '1px solid var(--glass-border)',
          borderRadius: 'var(--radius-md)',
          padding: '8px 16px',
          boxShadow: 'var(--glass-shadow)',
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          gap: '2px',
          zIndex: 5,
          pointerEvents: 'none',
          animation: 'fadeIn 0.15s ease'
        }}>
          <span style={{ fontSize: '0.75rem', color: 'hsl(var(--text-secondary))', fontWeight: 600 }}>
            {plotData[activeIdx]?.label}
          </span>
          <span style={{ fontSize: '1.05rem', color: 'hsl(var(--accent-color))', fontWeight: 800 }}>
            {formatFC(plotData[activeIdx]?.value ?? 0)}
          </span>
        </div>
      )}
    </div>
  );
};


// ─── 2. DualTrendChart (Two series: actual vs expected) ──────────────
export interface DualChartDataPoint {
  label: string;
  actual: number;
  expected: number;
}

interface DualChartProps {
  data: DualChartDataPoint[];
  height?: number;
  colorActual?: string;
  colorExpected?: string;
}

export const DualTrendChart: React.FC<DualChartProps> = ({
  data,
  height = 200,
  colorActual  = 'hsl(var(--accent-color))',
  colorExpected = '#10b981',
}) => {
  const [activeIdx, setActiveIdx] = useState<number | null>(null);

  if (!data || data.length === 0) return null;

  const plotData = data.length === 1 ? [data[0], data[0]] : data;
  const width = 500;
  const padding = 40;
  const chartWidth = width - padding * 2;
  const chartHeight = height - padding * 2;

  const allVals = plotData.flatMap(d => [d.actual, d.expected]);
  const maxVal = Math.max(...allVals) * 1.15 || 100;

  const toY = (v: number) => padding + chartHeight - (v / maxVal) * chartHeight;

  const pts = plotData.map((d, i) => ({
    x: padding + (i / (plotData.length - 1)) * chartWidth,
    ya: toY(d.actual),
    ye: toY(d.expected),
    ...d,
  }));

  const pathActual   = pts.reduce((a, p, i) => i === 0 ? `M ${p.x} ${p.ya}` : `${a} L ${p.x} ${p.ya}`, '');
  const pathExpected = pts.reduce((a, p, i) => i === 0 ? `M ${p.x} ${p.ye}` : `${a} L ${p.x} ${p.ye}`, '');
  const areaActual   = pts.length > 0 ? `${pathActual} L ${pts[pts.length-1].x} ${height-padding} L ${pts[0].x} ${height-padding} Z` : '';

  return (
    <div style={{ position: 'relative', width: '100%' }}>
      {/* Legend */}
      <div style={{ display: 'flex', gap: '16px', justifyContent: 'flex-end', marginBottom: '6px', fontSize: '0.68rem' }}>
        <span style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
          <span style={{ width: '16px', height: '3px', backgroundColor: colorActual, display: 'inline-block', borderRadius: '2px' }} />
          Paiement
        </span>
        <span style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
          <span style={{ width: '16px', height: '3px', backgroundColor: colorExpected, display: 'inline-block', borderRadius: '2px', opacity: 0.8 }} />
          Commande
        </span>
      </div>
      <svg viewBox={`0 0 ${width} ${height}`} style={{ width: '100%', height: 'auto', overflow: 'visible' }}>
        <defs>
          <linearGradient id="dualGradient" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={colorActual} stopOpacity="0.3" />
            <stop offset="100%" stopColor={colorActual} stopOpacity="0.0" />
          </linearGradient>
        </defs>
        {/* Grid lines */}
        {[0, 0.25, 0.5, 0.75, 1].map((ratio, idx) => {
          const y = padding + ratio * chartHeight;
          const val = maxVal * (1 - ratio);
          return (
            <g key={idx} opacity="0.12">
              <line x1={padding} y1={y} x2={width-padding} y2={y} stroke="currentColor" strokeDasharray="4" />
              <text x={padding-8} y={y+4} textAnchor="end" fontSize="10" fill="currentColor" fontWeight="600">
                {val > 1000 ? `${(val/1000).toFixed(0)}k` : val.toFixed(0)}
              </text>
            </g>
          );
        })}
        {/* Area under actual */}
        <path d={areaActual} fill="url(#dualGradient)" />
        {/* Expected line (dashed) */}
        <path d={pathExpected} fill="none" stroke={colorExpected} strokeWidth="2" strokeDasharray="6 3" strokeLinecap="round" opacity="0.85" />
        {/* Actual line */}
        <path d={pathActual} fill="none" stroke={colorActual} strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" />
        {/* Points + hover */}
        {pts.map((p, idx) => (
          <g key={idx}>
            <circle cx={p.x} cy={p.ya} r={activeIdx === idx ? 6 : 4} fill={activeIdx===idx ? '#070c1c' : colorActual} stroke={colorActual} strokeWidth="2" style={{ cursor:'pointer', transition:'all 0.15s' }} />
            <circle cx={p.x} cy={p.ye} r={3} fill={colorExpected} opacity="0.85" />
            <rect x={p.x - chartWidth/(plotData.length*2)} y={padding} width={chartWidth/(plotData.length-1)} height={chartHeight} fill="transparent" style={{ cursor:'pointer' }}
              onMouseEnter={() => setActiveIdx(idx)} onMouseLeave={() => setActiveIdx(null)} />
          </g>
        ))}
        {/* X labels */}
        {pts.map((p, idx) => {
          if (data.length === 1 && idx === 1) return null;
          if (idx === 0 || idx === Math.floor(pts.length/2) || idx === pts.length-1) {
            return <text key={idx} x={p.x} y={height-padding+20} textAnchor="middle" fontSize="10" fill="currentColor" opacity="0.5" fontWeight="700">{p.label}</text>;
          }
          return null;
        })}
      </svg>
      {/* Tooltip */}
      {activeIdx !== null && (
        <div style={{ position:'absolute', top:'8px', left:'50%', transform:'translateX(-50%)', backgroundColor:'var(--glass-bg)', backdropFilter:'var(--glass-filter)', border:'1px solid var(--glass-border)', borderRadius:'var(--radius-md)', padding:'8px 16px', boxShadow:'var(--glass-shadow)', display:'flex', flexDirection:'column', alignItems:'center', gap:'4px', zIndex:5, pointerEvents:'none' }}>
          <span style={{ fontSize:'0.72rem', color:'hsl(var(--text-secondary))', fontWeight:600 }}>{plotData[activeIdx]?.label}</span>
          <span style={{ fontSize:'0.9rem', color:colorActual, fontWeight:800 }}>Paiement : {formatFC(plotData[activeIdx]?.actual ?? 0)}</span>
          <span style={{ fontSize:'0.8rem', color:colorExpected, fontWeight:700 }}>Commande : {formatFC(plotData[activeIdx]?.expected ?? 0)}</span>
        </div>
      )}
    </div>
  );
};

// ─── 3. TripleTrendChart (Three series: commande / paiement / CM brut) ──────
export interface TripleChartDataPoint {
  label: string;
  commande: number;
  paiement: number;
  cm: number;
}

interface TripleChartProps {
  data: TripleChartDataPoint[];
  height?: number;
}

export const TripleTrendChart: React.FC<TripleChartProps> = ({ data, height = 220 }) => {
  const [activeIdx, setActiveIdx] = useState<number | null>(null);

  if (!data || data.length === 0) return null;

  const plotData = data.length === 1 ? [data[0], data[0]] : data;
  const width = 520;
  const padL = 52, padR = 16, padT = 16, padB = 32;
  const chartW = width - padL - padR;
  const chartH = height - padT - padB;

  const allVals = plotData.flatMap(d => [d.commande, d.paiement, d.cm]);
  const maxVal = Math.max(...allVals) * 1.12 || 100;

  const toX = (i: number) => padL + (i / (plotData.length - 1)) * chartW;
  const toY = (v: number) => padT + chartH - (v / maxVal) * chartH;

  const pts = plotData.map((d, i) => ({
    x: toX(i), yC: toY(d.commande), yP: toY(d.paiement), yM: toY(d.cm), ...d,
  }));

  const makePath = (yKey: 'yC' | 'yP' | 'yM') =>
    pts.reduce((a, p, i) => i === 0 ? `M ${p.x} ${p[yKey]}` : `${a} L ${p.x} ${p[yKey]}`, '');

  const C_COMMANDE = 'hsl(var(--accent-color))';
  const C_PAIEMENT = '#10b981';
  const C_CM       = '#f59e0b';

  const gridRatios = [0, 0.25, 0.5, 0.75, 1];

  return (
    <div style={{ position: 'relative', width: '100%' }}>
      <div style={{ display: 'flex', gap: '18px', justifyContent: 'flex-end', marginBottom: '6px', fontSize: '0.68rem', flexWrap: 'wrap' }}>
        {[
          { label: 'Commande', color: C_COMMANDE },
          { label: 'Paiement', color: C_PAIEMENT },
          { label: 'CM Brut',  color: C_CM },
        ].map(({ label, color }) => (
          <span key={label} style={{ display: 'flex', alignItems: 'center', gap: '5px' }}>
            <span style={{ width: '18px', height: '3px', backgroundColor: color, display: 'inline-block', borderRadius: '2px' }} />
            <span style={{ color: 'hsl(var(--text-secondary))', fontWeight: 600 }}>{label}</span>
          </span>
        ))}
      </div>
      <svg viewBox={`0 0 ${width} ${height}`} style={{ width: '100%', height: 'auto', overflow: 'visible' }}>
        {/* Grid */}
        {gridRatios.map((ratio, idx) => {
          const y = padT + ratio * chartH;
          const val = maxVal * (1 - ratio);
          return (
            <g key={idx} opacity="0.12">
              <line x1={padL} y1={y} x2={width - padR} y2={y} stroke="currentColor" strokeDasharray="4" />
              <text x={padL - 6} y={y + 4} textAnchor="end" fontSize="10" fill="currentColor" fontWeight="600">
                {val >= 1e6 ? `${(val/1e6).toFixed(1)}M` : val >= 1e3 ? `${(val/1e3).toFixed(0)}k` : val.toFixed(0)}
              </text>
            </g>
          );
        })}
        {/* Lines */}
        <path d={makePath('yC')} fill="none" stroke={C_COMMANDE} strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
        <path d={makePath('yP')} fill="none" stroke={C_PAIEMENT} strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
        <path d={makePath('yM')} fill="none" stroke={C_CM}       strokeWidth="2"   strokeLinecap="round" strokeLinejoin="round" strokeDasharray="6 3" />
        {/* Dots + hover zones */}
        {pts.map((p, idx) => (
          <g key={idx}>
            <circle cx={p.x} cy={p.yC} r={activeIdx === idx ? 5 : 3.5} fill={activeIdx === idx ? '#070c1c' : C_COMMANDE} stroke={C_COMMANDE} strokeWidth="2" style={{ transition: 'all 0.15s' }} />
            <circle cx={p.x} cy={p.yP} r={activeIdx === idx ? 5 : 3.5} fill={activeIdx === idx ? '#070c1c' : C_PAIEMENT} stroke={C_PAIEMENT} strokeWidth="2" style={{ transition: 'all 0.15s' }} />
            <circle cx={p.x} cy={p.yM} r={activeIdx === idx ? 4 : 3}   fill={C_CM} opacity="0.9" />
            <rect x={p.x - chartW / (plotData.length * 2)} y={padT} width={chartW / (plotData.length - 1)} height={chartH} fill="transparent" style={{ cursor: 'pointer' }}
              onMouseEnter={() => setActiveIdx(idx)} onMouseLeave={() => setActiveIdx(null)} />
          </g>
        ))}
        {/* X labels */}
        {pts.map((p, idx) => {
          if (data.length === 1 && idx === 1) return null;
          if (idx === 0 || idx === Math.floor(pts.length / 2) || idx === pts.length - 1) {
            return <text key={idx} x={p.x} y={height - padB + 18} textAnchor="middle" fontSize="9" fill="currentColor" opacity="0.55" fontWeight="700">{p.label}</text>;
          }
          return null;
        })}
      </svg>
      {activeIdx !== null && (
        <div style={{ position: 'absolute', top: '28px', left: '50%', transform: 'translateX(-50%)', backgroundColor: 'var(--glass-bg)', backdropFilter: 'var(--glass-filter)', border: '1px solid var(--glass-border)', borderRadius: 'var(--radius-md)', padding: '8px 14px', boxShadow: 'var(--glass-shadow)', display: 'flex', flexDirection: 'column', gap: '3px', zIndex: 5, pointerEvents: 'none', minWidth: '170px' }}>
          <span style={{ fontSize: '0.72rem', color: 'hsl(var(--text-secondary))', fontWeight: 600, textAlign: 'center', marginBottom: '2px' }}>{plotData[activeIdx]?.label}</span>
          <span style={{ fontSize: '0.78rem', color: C_COMMANDE, fontWeight: 700 }}>Commande : {formatFC(plotData[activeIdx]?.commande ?? 0)}</span>
          <span style={{ fontSize: '0.78rem', color: C_PAIEMENT, fontWeight: 700 }}>Paiement : {formatFC(plotData[activeIdx]?.paiement ?? 0)}</span>
          <span style={{ fontSize: '0.78rem', color: C_CM,       fontWeight: 700 }}>CM Brut  : {formatFC(plotData[activeIdx]?.cm ?? 0)}</span>
        </div>
      )}
    </div>
  );
};

// ─── 4. YieldDoughnut (Interactive SVG Doughnut Chart) ─────────────
export interface DoughnutDataPoint {
  label: string;
  value: number;
  color: string;
}

interface DoughnutProps {
  data: DoughnutDataPoint[];
  size?: number;
}

export const YieldDoughnut: React.FC<DoughnutProps> = ({ data, size = 180 }) => {
  const [hoveredIdx, setHoveredIdx] = useState<number | null>(null);

  const total = data.reduce((acc, d) => acc + d.value, 0) || 1;
  const radius = 50;
  const strokeWidth = 14;
  const viewBoxSize = 140;
  
  let accumulatedAngle = 0;

  return (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '24px', flexWrap: 'wrap' }}>
      {/* SVG Doughnut */}
      <div style={{ position: 'relative', width: `${size}px`, height: `${size}px` }}>
        <svg viewBox={`0 0 ${viewBoxSize} ${viewBoxSize}`} style={{ width: '100%', height: '100%' }}>
          {data.map((d, idx) => {
            const percentage = d.value / total;
            const angle = percentage * 360;
            const strokeDasharray = `${(percentage * 2 * Math.PI * radius).toFixed(2)} ${(2 * Math.PI * radius).toFixed(2)}`;
            const strokeDashoffset = `${(-accumulatedAngle * 2 * Math.PI * radius / 360).toFixed(2)}`;
            
            accumulatedAngle += angle;

            const isHovered = hoveredIdx === idx;

            return (
              <circle
                key={idx}
                cx={viewBoxSize / 2}
                cy={viewBoxSize / 2}
                r={radius}
                fill="transparent"
                stroke={d.color}
                strokeWidth={isHovered ? strokeWidth + 3 : strokeWidth}
                strokeDasharray={strokeDasharray}
                strokeDashoffset={strokeDashoffset}
                transform={`rotate(-90 ${viewBoxSize / 2} ${viewBoxSize / 2})`}
                style={{
                  transition: 'all 0.3s ease',
                  cursor: 'pointer',
                }}
                onMouseEnter={() => setHoveredIdx(idx)}
                onMouseLeave={() => setHoveredIdx(null)}
              />
            );
          })}
        </svg>

        {/* Center label displaying total or active slice */}
        <div style={{
          position: 'absolute',
          top: '50%',
          left: '50%',
          transform: 'translate(-50%, -50%)',
          textAlign: 'center',
          pointerEvents: 'none',
          display: 'flex',
          flexDirection: 'column'
        }}>
          <span style={{ 
            fontSize: '0.75rem', 
            color: 'hsl(var(--text-secondary))', 
            textTransform: 'uppercase',
            fontWeight: 700,
            letterSpacing: '0.05em'
          }}>
            {hoveredIdx !== null ? data[hoveredIdx].label : 'Total Production'}
          </span>
          <span style={{ 
            fontSize: '1.4rem', 
            fontWeight: 800, 
            color: hoveredIdx !== null ? data[hoveredIdx].color : 'hsl(var(--text-primary))',
            transition: 'color 0.2s ease'
          }}>
            {hoveredIdx !== null 
              ? `${((data[hoveredIdx].value / total) * 100).toFixed(1)}%`
              : `${total} sacs`
            }
          </span>
          {hoveredIdx !== null && (
            <span style={{ fontSize: '0.8rem', color: 'hsl(var(--text-muted))', fontWeight: 600 }}>
              {data[hoveredIdx].value} sacs
            </span>
          )}
        </div>
      </div>

      {/* Custom Sleek Legend panel */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', minWidth: '140px' }}>
        {data.map((d, idx) => (
          <div 
            key={idx} 
            style={{ 
              display: 'flex', 
              alignItems: 'center', 
              gap: '8px', 
              cursor: 'pointer',
              opacity: hoveredIdx === null || hoveredIdx === idx ? 1 : 0.4,
              transition: 'opacity 0.2s ease'
            }}
            onMouseEnter={() => setHoveredIdx(idx)}
            onMouseLeave={() => setHoveredIdx(null)}
          >
            <span style={{ 
              width: '10px', 
              height: '10px', 
              borderRadius: '50%', 
              backgroundColor: d.color,
              display: 'inline-block'
            }} />
            <span style={{ fontSize: '0.85rem', fontWeight: 600, color: 'hsl(var(--text-secondary))' }}>
              {d.label}
            </span>
            <span style={{ fontSize: '0.85rem', fontWeight: 700, marginLeft: 'auto' }}>
              {d.value}s
            </span>
          </div>
        ))}
      </div>
    </div>
  );
};
