# Rapport dev-frontend — BUG-083 (« ventes passées ») — 2026-10-29

## Périmètre traité

Volet frontend du ticket BUG-083, après livraison backend par dev-backend (voir
`docs/qa/rapports/dev-backend-bug083-2026-10-29.md`). Fichiers touchés :
`frontend/src/api/services.ts`, `frontend/src/pages/dashboard/Settings.tsx`,
`frontend/src/pages/dashboard/Clients.tsx`, `frontend/src/pages/dashboard/Sales.tsx`.
Aucun fichier backend modifié.

Ticket passé à **CORRIGÉ** dans `docs/qa/REGISTRE_BUGS.md` (section « Correction (frontend) »
ajoutée sous la correction backend existante — jamais écrasée). **Jamais passé à VÉRIFIÉ** :
seul le testeur d'origine (testeur-ventes/testeur-clients-commissions/testeur-tresorerie) ou le
coordinateur peut le faire, conformément à CLAUDE.md §7.2/§7.3.

## Implémentation

1. **`src/api/services.ts`** : `SiteConfig.allow_backdated_sales: boolean` ajouté à l'interface.
   `salesApi.deliver(id, deliveredAt?)` accepte désormais un second paramètre optionnel
   (`AAAA-MM-JJ`), envoyé dans le corps (`{ delivered_at }`) seulement s'il est fourni —
   comportement par défaut (aucun argument) strictement inchangé. `salesApi.create` n'a pas eu
   besoin de changement : `Partial<Invoice>` couvre déjà `invoice_date`.

2. **`Settings.tsx`** : nouvelle carte « Ventes Passées (saisie rétroactive) » dans le formulaire
   de configuration générale, avec un toggle visuel identique aux autres interrupteurs de la page
   et une description explicative sous le toggle. Appliqué via le helper `set()` déjà utilisé pour
   tous les autres réglages (sauvegarde au clic sur « Enregistrer la Configuration », pas
   d'instantané comme `on_line` qui a un impact public immédiat différent). La page est déjà
   restreinte à ADMIN/DIRECTION par la navigation (`DashboardLayout.tsx`), cohérent avec le reste
   des réglages qui n'ont pas de filtrage par rôle individuel au-delà de l'accès à la page.

3. **`Clients.tsx`** (modale « Enregistrer commande ») : `allowBackdatedSales` chargé via
   `coreApi.config.get()` dans `loadClients()` (déjà appelé, pas de requête HTTP supplémentaire).
   Champ `<input type="date" max={aujourd'hui}>` visible seulement si le réglage est actif, état
   `orderDate` réinitialisé à chaque fermeture de la modale. `handleSaleSubmit` envoie
   `invoice_date` (création) et `delivered_at` (livraison immédiate qui suit, propre à cette page)
   seulement si une date différente d'aujourd'hui a été choisie.

4. **`Sales.tsx`** (formulaire de facturation facturier + file de livraison) :
   - Même pattern de chargement de `allowBackdatedSales`, ajouté au `Promise.all` existant de
     `loadData()`.
   - Champ de date optionnel dans le formulaire « Nouvelle Facture POS », visible seulement si le
     réglage est actif.
   - **Point technique traité explicitement** : la file de livraison est rechargée via
     `salesApi.list({ invoice_date: todayStr })` — une facture à date rétroactive serait donc
     invisible après un rechargement complet, empêchant sa livraison depuis cet écran. Corrigé en
     ajoutant localement la facture retournée par la création à l'état `queue` (sans appeler
     `loadData()` dans ce cas précis) ; de même après livraison, l'entrée est mise à jour localement
     plutôt que rechargée si sa date diffère d'aujourd'hui. Les factures datées d'aujourd'hui
     suivent exactement le chemin `loadData()` inchangé.
   - Action « Imprimer le reçu » : nouvelle fonction `handleDeliverClick`. Réglage désactivé →
     comportement strictement identique à avant (clic = livraison immédiate datée d'aujourd'hui).
     Réglage activé → petite modale (composant `Modal` partagé, visible sans défilement) proposant
     une date de livraison optionnelle (`max=aujourd'hui`) ; ne rien toucher = livraison datée
     d'aujourd'hui, exactement comme avant.

## Conventions (CLAUDE.md §4)

- Aucun nouveau `any` introduit.
- Tous les appels HTTP passent par `coreApi`/`salesApi` (`src/api/services.ts`), aucun axios direct
  ajouté.
- Interface entièrement en français, montants déjà formatés par le code existant (non touché).
- Aucune page n'a dépassé le seuil d'extraction (~1000 lignes) justifiant un sous-composant :
  `Sales.tsx` passe de 905 à ~960 lignes avec des ajouts ciblés ; `Clients.tsx`/`Settings.tsx` n'ont
  reçu que quelques dizaines de lignes chacun.

## Vérifications

- `npx tsc --noEmit` : aucune erreur.
- `npm run build` : build de production réussi (seul avertissement préexistant sur la taille du
  chunk legacy, sans rapport avec cette session).
- **Test manuel non exécuté en conditions réelles** : au moment de cette session, le backend
  (port 8000) et le frontend (port 5173) étaient déjà actifs avec des connexions établies actives
  (vérifié via `netstat`), signe probable d'une autre session agent en cours sur la même base
  `db.sqlite3`. Par prudence, je n'ai pas créé de facture de test contre cette base partagée.
  Étapes de vérification manuelle détaillées pour le testeur dans la fiche BUG-083 du registre
  (section « Correction (frontend) »).

## Hors périmètre signalé (pas une découverte cachée)

Le badge « Correction » dans l'écran Livre de Caisse Direction (`Treasury.tsx`) pour les
`CashbookEntry.is_correction=True` n'a pas été traité — non demandé dans le mandat reçu pour cette
session (limité à Settings/Clients/Sales). À ouvrir en ticket séparé si le coordinateur le juge
nécessaire avant la vérification finale de BUG-083.

## Fichiers modifiés

- `frontend/src/api/services.ts`
- `frontend/src/pages/dashboard/Settings.tsx`
- `frontend/src/pages/dashboard/Clients.tsx`
- `frontend/src/pages/dashboard/Sales.tsx`
- `docs/qa/REGISTRE_BUGS.md` (fiche BUG-083 : statut → CORRIGÉ, section « Correction (frontend) »
  ajoutée)
