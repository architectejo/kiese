# Vérification croisée Dev C : BUG-415, compléments BUG-412/413, spec 32 (2026-11-21)

Méthode : relecture des diffs (bdf2b2e, e30223c), `npx tsc --noEmit` (0 erreur), `npm run build` (OK), suites backend `commissions` + `clients` : 216 tests OK. Aucun navigateur : rendu réel et thèmes NON contrôlés.

| Ticket | Verdict |
|---|---|
| BUG-415 | VÉRIFIÉ (relecture) |
| BUG-412 (complément) | VÉRIFIÉ (note ajoutée) |
| BUG-413 (complément) | VÉRIFIÉ (note ajoutée) |

## BUG-415
- Sticky : conteneur de défilement = `div overflowX:auto` autour du tableau ; aucun ancêtre `overflow:hidden` dans le composant. `th` et `td` collés (en-tête inclus), `right:0`, `z-index:1`, fond `hsl(var(--bg-secondary))` défini dans dark, light, classic ; opaque ; règle `:hover` alignée. Uniquement `max-width:640px`.
- Impression/export non touchés (autres fenêtres).
- Réserves : fond de carte translucide vs fond opaque de la colonne (esthétique) ; la colonne masque une partie de Statut ; à voir à l'écran.

## Spec 32
`test.use` viewport 360x740 pour tout le fichier ; `sansDefilementHorizontal` ; test dédié avec `toBeInViewport({ratio:1})`. Seul le bouton œil (colonne Actions) est discriminant ; le bouton historique (colonne Client) est visible avec ou sans correctif. Sans sticky, l'œil est clippé par le wrapper : l'assertion échoue. Non rejoué ici.

## BUG-412 complément
Paramètres `period__month`/`period__year` omis si vides (« Tous les mois »), `period__node` conservé ; `resetKey` unique, un rechargement par changement ; erreurs via `commissionsQ.error` + Réessayer ; pagination 100 conservée ; filtres backend couverts par `test_bug511*` (déjà VÉRIFIÉ).

## BUG-413 complément
Message de repli neutre exact ; le détail serveur / erreurs de champ restent prioritaires.

Pas d'`any` nouveau ni d'axios direct dans les diffs relus.
