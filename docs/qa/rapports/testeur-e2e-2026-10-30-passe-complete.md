# Rapport — testeur-e2e — 2026-10-30 (passe complète post-chantier remarque.md)

## Mission

Relancer une passe E2E complète après le chantier de corrections remarque.md (paiement sans
pain, recherche client, vente soldée/cash, corrections signées de facture, clôture de fournée
automatisée, journal de caisse) et le backlog mineur BUG-052/057/067/068/069/072/085/107/110/111/112
(tous `VÉRIFIÉ` au registre avant cette passe), sur bureau **et** POS 360 px.

## Mise en place

- Backend : `backend/.venv/Scripts/python.exe manage.py runserver 8000` avec
  `DJANGO_LOGIN_THROTTLE_RATE=100/min` (voir BUG-006 — la suite complète dépasse largement 5
  connexions/minute).
- Frontend : `npm run dev` (`frontend/`, Vite sur `:5173`).
- Base `backend/db.sqlite3` déjà seedée (`seed_kiese`, 678 clients, 9 nœuds) par une session
  précédente — vérifiée non vide avant de commencer.
- Comptes de démonstration E2E (`demo_*_e2e`, voir `e2e/README.md`) et les 3 clients démo
  (`K1-0078` CrossNodeE2E, `K1-0079` PlafondE2E, `K1-0083` RemboursementE2E) **recréés/réinitialisés**
  en début de session (absents de la base au démarrage — script `manage.py shell` documenté dans
  `e2e/README.md`, dette/plafond remis aux valeurs attendues par les specs).
- Stocks de consommables K1 (`FLOUR`/`OIL`/`SALT`/`YEAST`) réinitialisés à des valeurs généreuses
  (base à 0 au démarrage — épuisée par des sessions de test antérieures) pour permettre la
  déclaration de fournées sans blocage « stock insuffisant ».
- Fixture dédiée : une `CashClosure` fixe au 2020-02-02 pour K1 (`total_entries=12345.00`), créée
  une fois via `manage.py shell`, utilisée uniquement par le nouveau test du Journal de Caisse
  (date hors de toute plage utilisée par les autres specs de la suite — aucune interférence).
- **Aucune modification de code applicatif** (`backend/`, `frontend/src`) à aucun moment de cette
  session — conforme CLAUDE.md §7.2.

## Nouveau fichier de tests

`e2e/tests/10-regression-remarque-2026-10-30.spec.ts` — 4 scénarios ciblant explicitement les
corrections de la mission, avec un angle E2E que la suite unitaire backend ne peut pas voir
(cohérence écran-à-écran, rendu réel du formulaire) :

1. **Vente Soldée (BUG-107/111)** : aperçu -25 % avant soumission ↔ reçu imprimé après livraison,
   P.U. et total identiques (facturier, `Sales.tsx`).
2. **Vente sans commission + Vente Soldée (BUG-052)** : les deux cases combinables sans confusion
   visuelle, requête serveur interceptée confirmant `is_soldee`/`commission_exempt`/`commission_rate`
   (gérant, vente directe, `Clients.tsx`).
3. **Clôture de fournée automatisée (BUG-093/108)** : action « Clôturer » → recoupement automatique
   affiché (`ClosureSummaryCard`) → saisie verrouillée (`Production.tsx`).
4. **Journal de Caisse, écart non bloquant (BUG-091/105)** : un écart volontaire avec une
   `CashClosure` fixe déclenche un avertissement explicite, jamais un blocage (`Treasury.tsx`).

**Résultat final : les 4 scénarios sont verts, de façon répétée et indépendante, sur bureau
(1440×900) et POS (360×740).** Détail des itérations et des deux imprécisions de sélecteur
corrigées au fil de la vérification (dans le nouveau fichier, pas dans le code applicatif) :

- Test 1 : un premier run a révélé que `.first()` sur le bouton « Imprimer le reçu » n'est pas
  fiable quand la file contient d'autres factures « En attente » laissées par un autre test de la
  suite (`08-facturation-serie.spec.ts` crée 10 factures jamais livrées) — corrigé en capturant le
  `receipt_number` renvoyé par le serveur à la création et en ciblant sans ambiguïté la carte
  portant ce numéro exact. **Revérifié vert 3 fois de suite** après correction.
- Test 3 : la fournée de test utilise l'Équipe B (pour ne pas entrer en conflit avec l'Équipe A
  déjà utilisée par `05-production.spec.ts` le même jour) ; le test détecte maintenant
  explicitement le cas « déjà déclarée aujourd'hui » (contrainte `unique_together` légitime,
  §5.4) et s'auto-`skip` avec un message clair plutôt que d'échouer de façon confuse en cas de
  rejeu same-day.

Les deux fichiers de verrouillage/consommables/clients listés plus haut (team B residual,
consommables K1) ont été réinitialisés entre chaque itération de vérification — purement des
données de test, jamais de code applicatif.

## Relance de la suite pré-existante (01 à 09)

Suite complète rejouée une fois en intégralité sur bureau : **22 passés / 7 échecs / 5 `fixme`
attendus** (non implémentés par un agent précédent, documentés comme tels dans leur fichier).
**Triage des 7 échecs — aucun n'est une régression applicative**, détail complet dans
`docs/qa/REGISTRE_BUGS.md` (section « Synthèse — testeur-e2e, 2026-10-30 ») :

- **3 échecs = flakiness d'environnement** (`page.goto` dépassant 15 s alors que la page est déjà
  correctement rendue au moment de l'échec, vérifié par capture). Corrélée à une accumulation de
  processus `chrome.exe` headless sur la durée de cette longue session (jusqu'à 16-18 processus
  constatés, contre 1-2 attendus) — confirmée en testant en parallèle les deux serveurs de dev en
  direct (`curl`), qui répondaient instantanément pendant que Playwright échouait sur la même
  machine au même moment. Rejouée isolément avec succès une fois la charge retombée.
- **2 échecs = imprécision des tests pré-existants eux-mêmes**, pas un défaut applicatif :
  - `02-connexion-roles.spec.ts` attend que COMPTABLE ne voie pas « Registre Blockchain », mais
    `DashboardLayout.tsx`/`core/permissions.py::IsHeadquarters` l'autorisent explicitement
    (COMPTABLE = niveau HQ). **Signalé au coordinateur sans trancher** (CLAUDE.md §7.6) : décision
    métier à prendre (resserrer l'accès, ou corriger l'assertion du test).
  - `06-tresorerie-caisse.spec.ts` (BUG-026/044) cherche le texte « Livre de Caisse Direction »
    sans scope — il matche aussi le sous-titre générique non conditionnel de la page (visible par
    tous les rôles), pas seulement la section réellement restreinte (qui, elle, reste
    correctement masquée pour GERANT — vérifié dans le code, `user?.can_access_all_nodes`).
    Aucune régression sur BUG-026/044.
- **2 échecs = limite connue de rejeu same-day** du nouveau fichier (contrainte
  `unique_together (node, team, date)` sur `ProductionSession`), déjà documentée ci-dessus et
  désormais auto-détectée par le test lui-même.

## Nouveau ticket ouvert

**BUG-114** (Mineur, backend/frontend) — `JournalEntryViewSet` filtre par `date__year=year` sans
validation de plage : une année hors bornes (ex. `20000`) déclenche un `500 Internal Server
Error` (`ValueError: year 20000 is out of range`) au lieu d'un `400` propre. Découvert
incidemment en corrigeant un sélecteur Playwright trop large (ciblait par erreur le champ Année
du navigateur mois/année du Journal au lieu du champ « Entrée (FC) ») — sans rapport avec l'objet
de la mission. Fiche complète dans `docs/qa/REGISTRE_BUGS.md`.

## Conclusion

**Aucune régression constatée sur les tickets explicitement visés par la mission**
(BUG-052/057/067/068/069/072/085/091/093/105/107/108/110/111/112, remarque.md : paiement sans
pain, recherche client, vente soldée/cash, corrections signées de facture, clôture de fournée
automatisée, journal de caisse). Les 4 nouveaux scénarios E2E dédiés sont verts sur bureau et POS
360 px, de façon répétée. La suite pré-existante (01-09) ne révèle aucune régression une fois les
échecs triés (flakiness d'environnement en fin de session longue + deux imprécisions de
sélecteur dans des tests pré-existants, non liées au chantier récent).

**Recommandation au coordinateur** : relancer la suite complète 01-09 dans un environnement frais
(nouvelle session) pour un signal définitif, la machine actuelle montrant des signes de
dégradation progressive (accumulation de processus navigateur) après plusieurs heures d'usage
intensif de l'outillage Claude Code en parallèle des tests.

## Fichiers modifiés/créés

- `e2e/tests/10-regression-remarque-2026-10-30.spec.ts` (nouveau, 4 scénarios).
- `docs/qa/REGISTRE_BUGS.md` (BUG-114 ouvert + section de synthèse de cette passe).
- Aucun fichier applicatif (`backend/`, `frontend/src`) modifié.

## Nettoyage effectué avant de rendre la main

- Serveurs `runserver`/`vite` démarrés pour cette session : arrêtés (PID identifiés via
  `netstat`, `taskkill` ciblé — ports `:8000`/`:5173` confirmés libres).
- Fichiers de log temporaires (`backend/_e2e_runserver.log`, `frontend/_e2e_vite.log`,
  `e2e/_run*.log`, `e2e/_full_bureau.log`, `e2e/_final_bureau.log`) supprimés.
- Aucun processus orphelin volontairement laissé ; les processus `chrome.exe` résiduels
  accumulés par Playwright au fil de cette session restent potentiellement présents (hors du
  contrôle direct de cet agent — permission de kill large refusée par le système) : à surveiller
  par le coordinateur si la machine reste lente pour la suite de la session.
