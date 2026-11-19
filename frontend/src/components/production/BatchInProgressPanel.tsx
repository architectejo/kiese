import React, { useCallback, useEffect, useState } from 'react';
import { FiAlertTriangle, FiGrid, FiRefreshCw } from 'react-icons/fi';
import { productionApi, ProductionSession, ServiceTeam } from '@/api/services';
import { getErrorDetail, isTeamNotAssignedError } from '@/api/errors';
import { useTeamAssignmentStore, TEAM_NOT_ASSIGNED_MESSAGE } from '@/store/teamAssignmentStore';
import { mergeSessionLines } from '@/components/production/mergeSessionLines';

// BUG-306 : déclaration d'une fournée par NOMBRE DE SACS seul, fournée « en cours » pour l'équipe
// en service, objectif = sacs x valeur du sac, barre de progression, pains par catégorie mis à jour
// automatiquement par le serveur (affichage seulement).

const REFRESH_MS = 15000;

const fc = (n: number) => `${Math.round(n).toLocaleString('fr-FR')} FC`;

export interface ProgressTone { color: string; label: string }

/** Seuils validés : < 25 % rouge, < 50 % orange, < 100 % jaune, >= 100 % vert. */
export function progressTone(pct: number): ProgressTone {
  if (pct >= 100) return { color: 'hsl(142 71% 38%)', label: 'vert' };
  if (pct >= 50) return { color: 'hsl(48 96% 46%)', label: 'jaune' };
  if (pct >= 25) return { color: 'hsl(25 95% 53%)', label: 'orange' };
  return { color: 'hsl(0 72% 51%)', label: 'rouge' };
}

export const ProgressBar: React.FC<{ pct: number; valueFc: number; objectiveFc: number }> = ({ pct, valueFc, objectiveFc }) => {
  const tone = progressTone(pct);
  const shown = Math.min(Math.max(pct, 0), 100);
  const text = `Fournée à ${pct.toFixed(0)} % : ${fc(valueFc)} sur ${fc(objectiveFc)} (${tone.label})`;
  return (
    <div>
      <div
        role="progressbar"
        aria-label="Avancement de la fournée"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(shown)}
        aria-valuetext={text}
        title={text}
        style={{ height: '18px', borderRadius: '9px', backgroundColor: 'hsl(var(--border-color))', overflow: 'hidden' }}
      >
        <div style={{ height: '100%', width: `${shown}%`, backgroundColor: tone.color, transition: 'width 0.4s ease' }} />
      </div>
      <div style={{ display: 'flex', justifyContent: 'space-between', flexWrap: 'wrap', gap: '6px', marginTop: '6px', fontSize: '0.8rem' }}>
        <span style={{ fontWeight: 800, color: tone.color }}>{pct.toFixed(0)} %</span>
        <span style={{ fontWeight: 700 }}>{fc(valueFc)} / {fc(objectiveFc)}</span>
      </div>
    </div>
  );
};

interface Props {
  /** Boulangerie consultée (code ou id selon le filtre de la page). */
  nodeFilter?: string;
  /** Compte rattaché à une boulangerie (seul à pouvoir déclarer). */
  canDeclare: boolean;
  workDate: string;
  rotationActive: boolean;
  serviceTeam: ServiceTeam | null | undefined;
  onServiceTeam: (t: ServiceTeam | null) => void;
  /** Valeur d'un sac en FC (information avant déclaration). */
  /** null tant que la valeur du sac n'est pas chargée (BUG-311). */
  sacValueFc: number | null;
  onChanged: () => void;
}

const labelStyle: React.CSSProperties = {
  display: 'block', fontSize: '0.7rem', fontWeight: 700, color: 'hsl(var(--text-secondary))',
  marginBottom: '4px', textTransform: 'uppercase',
};

export const BatchInProgressPanel: React.FC<Props> = ({
  nodeFilter, canDeclare, workDate, rotationActive, serviceTeam, onServiceTeam, sacValueFc, onChanged,
}) => {
  const requestTeamAssignment = useTeamAssignmentStore(st => st.requestAssignment);
  const [sessions, setSessions] = useState<ProductionSession[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [selTeam, setSelTeam] = useState<ServiceTeam>('A');
  const [sacs, setSacs] = useState('');
  const [salt, setSalt] = useState('');
  const [yeast, setYeast] = useState('');
  const [oil, setOil] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [newTotal, setNewTotal] = useState('');

  const load = useCallback(async () => {
    try {
      const params: Record<string, string> = { date: workDate };
      if (nodeFilter) params.node = nodeFilter;
      const { data } = await productionApi.sessions.list(params);
      setSessions(Array.isArray(data) ? data : []);
      setLoadError(null);
    } catch (err: unknown) {
      setLoadError(getErrorDetail(err, 'Impossible de charger la fournée en cours.'));
    } finally {
      setLoading(false);
    }
  }, [nodeFilter, workDate]);

  // Rafraîchissement périodique : la barre avance à chaque livraison confirmée.
  useEffect(() => {
    setLoading(true);
    void load();
    const id = setInterval(() => { void load(); }, REFRESH_MS);
    return () => clearInterval(id);
  }, [load]);

  const team: ServiceTeam | null | undefined = rotationActive ? serviceTeam : selTeam;
  const current = sessions.find(s =>
    s.auto_track && !s.is_closed && (team == null || s.team === team),
  ) ?? null;

  const consumables = () => ([
    ['SALT', salt], ['YEAST', yeast], ['OIL', oil],
  ] as const)
    .filter(([, q]) => q !== '' && parseFloat(q.replace(',', '.')) > 0)
    .map(([consumable_type, q]) => ({ consumable_type, quantity: parseFloat(q.replace(',', '.')) }));

  const handleTeamError = (err: unknown): boolean => {
    if (isTeamNotAssignedError(err)) {
      setError(TEAM_NOT_ASSIGNED_MESSAGE.replace('avant de facturer', 'avant de déclarer une fournée'));
      requestTeamAssignment();
      return true;
    }
    return false;
  };

  const handleDeclare = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (saving) return;
    setError(null);
    const n = parseFloat(sacs.replace(',', '.'));
    if (!canDeclare) { setError('Compte non assigné à une boulangerie.'); return; }
    if (!(n > 0)) { setError('Indiquez le nombre de sacs de farine.'); return; }
    setSaving(true);
    try {
      if (rotationActive) {
        const { data: assignment } = await productionApi.teamAssignment.get();
        onServiceTeam(assignment.team);
        if (assignment.team === null) {
          setError(TEAM_NOT_ASSIGNED_MESSAGE.replace('avant de facturer', 'avant de déclarer une fournée'));
          requestTeamAssignment();
          return;
        }
      }
      const cons = consumables();
      await productionApi.sessions.create({
        flour_sacks_used: n.toString(),
        // Rotation : le serveur décide de la date et de l'équipe (BUG-195).
        ...(rotationActive ? {} : { date: workDate, team: selTeam }),
        ...(cons.length > 0 ? { consumables_used: cons } : {}),
      });
      setSacs(''); setSalt(''); setYeast(''); setOil('');
      await load();
      onChanged();
    } catch (err: unknown) {
      if (!handleTeamError(err)) setError(getErrorDetail(err, 'Erreur lors de la déclaration de la fournée.'));
    } finally {
      setSaving(false);
    }
  };

  const handleIncrease = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (saving || !current) return;
    setError(null);
    const n = parseFloat(newTotal.replace(',', '.'));
    const currentSacs = parseFloat(current.flour_sacks_used);
    if (!(n > 0)) { setError('Indiquez le nouveau nombre total de sacs.'); return; }
    if (n <= currentSacs) { setError(`Le nouveau total doit dépasser ${currentSacs.toLocaleString('fr-FR')} sacs déjà déclarés.`); return; }
    setSaving(true);
    try {
      await productionApi.sessions.update(current.id, { flour_sacks_used: n.toString() });
      setNewTotal('');
      await load();
      onChanged();
    } catch (err: unknown) {
      setError(getErrorDetail(err, "Impossible d'augmenter le nombre de sacs."));
    } finally {
      setSaving(false);
    }
  };

  const inputStyle: React.CSSProperties = { fontSize: '1rem', height: '44px', padding: '0 10px' };
  const bigBtn: React.CSSProperties = { minHeight: '48px', fontSize: '0.95rem', fontWeight: 800, width: '100%' };

  const objective = current ? (current.objective_fc ?? current.theoretical_yield ?? 0) : 0;
  const progressValue = current?.progress_value_fc ?? 0;
  const pct = current ? parseFloat(current.progress_pct ?? '0') || 0 : 0;

  return (
    <div className="glass-card" style={{ padding: '14px' }} data-testid="batch-in-progress-panel">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '8px', marginBottom: '12px', flexWrap: 'wrap' }}>
        <h2 style={{ fontSize: '0.95rem', fontWeight: 800, display: 'flex', alignItems: 'center', gap: '6px', margin: 0 }}>
          <FiGrid style={{ color: 'hsl(var(--accent-color))' }} />
          {current ? 'Fournée en cours' : 'Déclaration de Fournée'}
        </h2>
        <button type="button" className="btn btn-secondary" onClick={() => { void load(); }} aria-label="Actualiser la fournée en cours" style={{ minHeight: '36px', display: 'flex', alignItems: 'center', gap: '5px', fontSize: '0.75rem' }}>
          <FiRefreshCw style={{ animation: loading ? 'spin 1s linear infinite' : 'none' }} /> Actualiser
        </button>
      </div>

      {loadError && (
        <div role="alert" style={{ display: 'flex', gap: '6px', alignItems: 'center', fontSize: '0.75rem', color: 'hsl(var(--color-danger))', backgroundColor: 'hsl(var(--color-danger) / 0.08)', padding: '8px 10px', borderRadius: 'var(--radius-sm)', marginBottom: '8px' }}>
          <FiAlertTriangle style={{ flexShrink: 0 }} /> {loadError}
        </div>
      )}

      {loading && !current && !loadError && (
        <div style={{ color: 'hsl(var(--text-secondary))', fontSize: '0.8rem', padding: '8px 0' }}>Chargement de la fournée…</div>
      )}

      {current ? (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px', fontSize: '0.8rem', alignItems: 'center' }}>
            <span className="badge badge-info">Équipe {current.team}</span>
            <span style={{ fontWeight: 700 }}>{parseFloat(current.flour_sacks_used).toLocaleString('fr-FR')} sacs de farine</span>
          </div>

          <div style={{ border: '1px solid hsl(var(--border-color))', borderRadius: 'var(--radius-sm)', padding: '12px', backgroundColor: 'hsl(var(--bg-tertiary))' }}>
            <div style={{ fontSize: '0.7rem', fontWeight: 700, textTransform: 'uppercase', color: 'hsl(var(--text-secondary))' }}>Montant à atteindre</div>
            <div style={{ fontSize: '1.5rem', fontWeight: 900, margin: '2px 0 10px' }} data-testid="batch-objective">{fc(objective)}</div>
            <ProgressBar pct={pct} valueFc={progressValue} objectiveFc={objective} />
          </div>

          <div>
            <div style={{ fontSize: '0.7rem', fontWeight: 700, textTransform: 'uppercase', color: 'hsl(var(--text-secondary))', marginBottom: '4px' }}>
              Pains par catégorie (mis à jour automatiquement à chaque livraison)
            </div>
            {current.lines.length === 0 ? (
              <div style={{ fontSize: '0.78rem', color: 'hsl(var(--text-muted))' }}>Aucune vente livrée pour le moment.</div>
            ) : (
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(110px, 1fr))', gap: '6px' }}>
                {mergeSessionLines(current.lines).map(l => (
                  <div key={l.bread_price} style={{ backgroundColor: 'hsl(var(--bg-tertiary))', borderRadius: '4px', padding: '6px 8px' }}>
                    <div style={{ fontSize: '0.68rem', fontWeight: 700, color: 'hsl(var(--text-muted))' }}>{l.bread_price_display ?? `Pain ${l.bread_price}`}</div>
                    <div style={{ fontWeight: 800, fontSize: '0.95rem' }}>{l.quantity.toLocaleString('fr-FR')} pains</div>
                  </div>
                ))}
              </div>
            )}
          </div>

          {canDeclare && (
            <form onSubmit={handleIncrease} style={{ display: 'flex', flexDirection: 'column', gap: '8px', borderTop: '1px solid hsl(var(--border-color))', paddingTop: '10px' }}>
              <label htmlFor="batch-new-total" style={labelStyle}>Augmenter les sacs (nouveau total)</label>
              <input id="batch-new-total" type="number" inputMode="decimal" step="0.01" min={0.01} value={newTotal} onChange={e => setNewTotal(e.target.value)} placeholder={`Plus de ${parseFloat(current.flour_sacks_used)}`} className="form-input" style={inputStyle} />
              <button type="submit" className="btn btn-primary" disabled={saving} style={bigBtn}>{saving ? 'Enregistrement…' : 'Mettre à jour les sacs'}</button>
            </form>
          )}
        </div>
      ) : (
        !loading && (
          <form onSubmit={handleDeclare} style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
            <p style={{ fontSize: '0.78rem', color: 'hsl(var(--text-secondary))', margin: 0 }}>
              Aucune fournée en cours. Indiquez seulement le nombre de sacs : le montant à atteindre est calculé
              {sacValueFc !== null ? `(1 sac = ${fc(sacValueFc)}) ` : ''}et les pains par catégorie se remplissent à chaque livraison.
            </p>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: '10px' }}>
              <div>
                <span style={labelStyle}>Équipe</span>
                {rotationActive ? (
                  <div className="form-input" data-testid="service-team-locked" style={{ ...inputStyle, display: 'flex', alignItems: 'center', fontWeight: 700, fontSize: '0.85rem' }}>
                    {serviceTeam === undefined ? 'Équipe de service : chargement…' : serviceTeam === null ? 'Équipe de service : non désignée' : `Équipe de service : ${serviceTeam}`}
                  </div>
                ) : (
                  <select value={selTeam} onChange={e => setSelTeam(e.target.value as ServiceTeam)} className="form-input" style={inputStyle} aria-label="Équipe">
                    <option value="A">Équipe A</option>
                    <option value="B">Équipe B</option>
                  </select>
                )}
              </div>
              <div>
                <label htmlFor="batch-sacs" style={labelStyle}>Nombre de sacs de farine *</label>
                <input id="batch-sacs" type="number" inputMode="decimal" step="0.01" min={0.01} value={sacs} onChange={e => setSacs(e.target.value)} placeholder="4" className="form-input" style={inputStyle} />
              </div>
            </div>
            {parseFloat(sacs) > 0 && sacValueFc !== null && (
              <div style={{ fontSize: '0.85rem' }}>Montant à atteindre : <strong>{fc(parseFloat(sacs) * sacValueFc)}</strong></div>
            )}
            <div style={{ borderTop: '1px solid hsl(var(--border-color))', paddingTop: '8px' }}>
              <span style={labelStyle}>Consommables utilisés (facultatif)</span>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(100px, 1fr))', gap: '8px' }}>
                <input type="number" inputMode="decimal" min="0" step="1" value={salt} onChange={e => setSalt(e.target.value)} placeholder="Sel (g)" aria-label="Sel en grammes" className="form-input" style={inputStyle} />
                <input type="number" inputMode="decimal" min="0" step="0.01" value={yeast} onChange={e => setYeast(e.target.value)} placeholder="Levure (paquets)" aria-label="Levure en paquets" className="form-input" style={inputStyle} />
                <input type="number" inputMode="decimal" min="0" step="0.01" value={oil} onChange={e => setOil(e.target.value)} placeholder="Huile (litres)" aria-label="Huile en litres" className="form-input" style={inputStyle} />
              </div>
            </div>
            <button type="submit" className="btn btn-primary" disabled={saving || !canDeclare} style={bigBtn}>{saving ? 'Enregistrement…' : 'Enregistrer la Fournée'}</button>
          </form>
        )
      )}

      {error && (
        <div role="alert" style={{ display: 'flex', alignItems: 'center', gap: '6px', backgroundColor: 'hsl(var(--color-danger) / 0.1)', border: '1px solid hsl(var(--color-danger) / 0.3)', borderRadius: 'var(--radius-sm)', padding: '8px 10px', fontSize: '0.78rem', color: 'hsl(var(--color-danger))', marginTop: '10px' }}>
          <FiAlertTriangle style={{ flexShrink: 0 }} /> <span>{error}</span>
        </div>
      )}
    </div>
  );
};
