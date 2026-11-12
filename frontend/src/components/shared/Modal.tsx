import React, { useEffect, useRef } from 'react';
import { createPortal } from 'react-dom';
import { FiX } from 'react-icons/fi';

const FOCUSABLE_SELECTOR =
  'a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])';

// BUG-157 : nombre de <Modal> ouverts en même temps. Deux boîtes peuvent
// coexister (annonce de clôture automatique par-dessus la modale forcée de
// l'autre équipe) : fermer la première ne doit pas retirer le verrou de
// défilement `body.modal-open` tant que la seconde est encore ouverte.
let openModalCount = 0;

export interface ModalProps {
  isOpen: boolean;
  onClose: () => void;
  title?: string;
  subtitle?: React.ReactNode;
  children: React.ReactNode;
  footer?: React.ReactNode;
  maxWidth?: string;
  closeOnBackdropClick?: boolean;
  showCloseButton?: boolean;
  /** Content slot padding override. Leave unset to use the default
   *  responsive padding (shrinks on small screens). Pass '0' when children
   *  bring their own fully custom header/body/footer layout (e.g. tabs,
   *  dynamic icons) — those manage their own internal padding. */
  contentPadding?: string;
  /** BUG-188 : la boîte reste MONTÉE (l'état local de ses enfants est conservé)
   *  mais masquée (`display: none`) et neutralisée : pas de verrou de défilement,
   *  pas de piège de focus, pas de gestion d'Échap. Sert à céder la place à une
   *  boîte plus prioritaire (désignation d'équipe) sans perdre une saisie en cours. */
  suspended?: boolean;
}

/**
 * Shared modal, rendered via a portal directly under document.body.
 *
 * Portaling matters here: page content sits inside DashboardLayout's
 * `.animate-fade-in` wrapper, whose fade animation applies a `transform`.
 * Any non-`none` transform on an ancestor creates a CSS containing block
 * for `position: fixed` descendants, so a modal rendered inline in page
 * JSX would be positioned relative to that (scrollable) wrapper instead
 * of the viewport — the "modal opens off-screen, need to scroll" bug.
 * Rendering into document.body sidesteps that class of bug entirely,
 * regardless of what ancestors a page later adds.
 */
export const Modal: React.FC<ModalProps> = ({
  isOpen,
  onClose,
  title,
  subtitle,
  children,
  footer,
  maxWidth = '520px',
  closeOnBackdropClick = true,
  showCloseButton = true,
  contentPadding,
  suspended = false,
}) => {
  const cardRef = useRef<HTMLDivElement>(null);
  const previouslyFocused = useRef<HTMLElement | null>(null);

  // Callers almost always pass `onClose={() => ...}` inline, so its identity
  // changes on every parent re-render (e.g. typing in a field inside the
  // modal). Reading it through a ref keeps Escape/backdrop-close working
  // with the latest handler without making the effect below re-run on every
  // keystroke — re-running it used to steal focus back to the first field
  // each time, kicking the cursor out of whatever input was being typed in.
  const onCloseRef = useRef(onClose);
  useEffect(() => { onCloseRef.current = onClose; }, [onClose]);

  const active = isOpen && !suspended;

  useEffect(() => {
    if (!active) return;
    openModalCount += 1;
    document.body.classList.add('modal-open');
    previouslyFocused.current = document.activeElement as HTMLElement | null;

    // Wait a tick so the portal's children are in the DOM before we probe for them.
    const raf = requestAnimationFrame(() => {
      const first = cardRef.current?.querySelector<HTMLElement>(FOCUSABLE_SELECTOR);
      (first ?? cardRef.current)?.focus();
    });

    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        onCloseRef.current();
        return;
      }
      if (e.key === 'Tab' && cardRef.current) {
        const focusables = Array.from(cardRef.current.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR));
        if (focusables.length === 0) return;
        const first = focusables[0];
        const last = focusables[focusables.length - 1];
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first.focus();
        }
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => {
      cancelAnimationFrame(raf);
      openModalCount = Math.max(0, openModalCount - 1);
      if (openModalCount === 0) document.body.classList.remove('modal-open');
      window.removeEventListener('keydown', onKeyDown);
      previouslyFocused.current?.focus?.();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active]);

  if (!isOpen) return null;

  return createPortal(
    <div
      className="modal-backdrop"
      aria-hidden={suspended || undefined}
      onClick={closeOnBackdropClick ? onClose : undefined}
      style={{
        position: 'fixed',
        inset: 0,
        backgroundColor: 'rgba(0, 0, 0, 0.6)',
        backdropFilter: 'blur(8px)',
        zIndex: 1000, // mirrors --z-modal-backdrop in styles/index.css
        display: suspended ? 'none' : 'flex',
        alignItems: 'center',
        justifyContent: 'center',
      }}
    >
      <div
        ref={cardRef}
        tabIndex={-1}
        onClick={(e) => e.stopPropagation()}
        className="animate-scale-in"
        role="dialog"
        aria-modal="true"
        aria-label={title}
        style={{
          position: 'relative',
          width: '100%',
          maxWidth,
          maxHeight: '90vh',
          display: 'flex',
          flexDirection: 'column',
          backgroundColor: 'hsl(var(--bg-secondary))',
          border: '1px solid hsl(var(--border-color))',
          borderRadius: 'var(--radius-lg)',
          boxShadow: 'var(--glass-shadow)',
          overflow: 'hidden',
          outline: 'none',
        }}
      >
        {(title || showCloseButton) && (
          <div
            className="modal-header"
            style={{
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'flex-start',
              gap: '12px',
              borderBottom: title ? '1px solid hsl(var(--border-color))' : 'none',
              flexShrink: 0,
            }}
          >
            <div style={{ minWidth: 0 }}>
              {title && (
                <h2 style={{ fontSize: '1.2rem', fontWeight: 800, color: 'hsl(var(--text-primary))', letterSpacing: '-0.02em' }}>
                  {title}
                </h2>
              )}
              {subtitle && (
                <p style={{ fontSize: '0.8rem', color: 'hsl(var(--text-secondary))', marginTop: '4px' }}>
                  {subtitle}
                </p>
              )}
            </div>
            {showCloseButton && (
              <button
                onClick={onClose}
                aria-label="Fermer"
                style={{
                  border: 'none',
                  background: 'hsl(var(--bg-tertiary))',
                  color: 'hsl(var(--text-secondary))',
                  padding: '8px',
                  borderRadius: '50%',
                  cursor: 'pointer',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  fontSize: '1rem',
                  flexShrink: 0,
                }}
              >
                <FiX />
              </button>
            )}
          </div>
        )}

        <div
          className="modal-body"
          style={{
            ...(contentPadding !== undefined ? { padding: contentPadding } : {}),
            overflowY: 'auto',
            flex: 1,
            minHeight: 0,
          }}
        >
          {children}
        </div>

        {footer && (
          <div
            className="modal-footer"
            style={{
              borderTop: '1px solid hsl(var(--border-color))',
              flexShrink: 0,
              display: 'flex',
              gap: '12px',
              justifyContent: 'flex-end',
            }}
          >
            {footer}
          </div>
        )}
      </div>
    </div>,
    document.body
  );
};
