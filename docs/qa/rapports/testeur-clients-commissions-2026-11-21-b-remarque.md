# Testeur clients et commissions (dev B) — passage `[]` vers `[c]` de remarque.md et BUG-507 — 2026-11-21

Aucun code applicatif ni `remarque.md` modifiés. Tests exécutés (base isolée `DB_NAME`, `DJANGO_DEBUG=True`) :
`clients.tests.test_verif_bug400_testeur_clients_commissions`, `test_verif_bug289_295_2026_11_15`, `test_bug400_client_history` = 39 tests, OK.

## 1. Tableau des lignes (message #09-A)

| Début de la ligne | Tickets | Verdict | Raison |
|---|---|---|---|
| « Au niveau de "Configuration" les valeurs du formulaire "§2.3 — Algorithme des Commissions (CM)" sont propres à chaque boulangerie, le frais de carte… » | BUG-289 (VÉRIFIÉ), 291 (VÉRIFIÉ), 295 (VÉRIFIÉ) | **laisser `[]`** | Seule la cotisation sociale est par boulangerie (`Node.monthly_social_contribution`, Paramètres > Boulangeries). Les trois champs du formulaire §2.3 (`ConfigForm.tsx` : taux de commission par défaut, taux de cotisation sociale, frais d'imprimés) sont dans `Config`, singleton global : aucune valeur par boulangerie, et `commissions/views.py` lit `config.print_fee` global. Le « frais de carte » est volontairement à 0 (BUG-291, décision client du 2026-11-14 « on n'a plus besoin de carte client »), ce qui contredit la remarque : question à poser (voir ci-dessous). Les tickets vérifiés ne couvrent pas la remarque entière. |
| « Dans "Commissions CM" on doit prendre en compte les valeurs de carte et cotisation sociale qui dépendent de la boulangerie à déduire de la commission de chaque client, le filtre doit aussi se faire sur le mois de l'année. » | BUG-289 (VÉRIFIÉ), 291 (VÉRIFIÉ) | **laisser `[]`** | Cotisation par boulangerie déduite : faite (retenue = valeur du nœud, `deduction_social`). Carte : déduction supprimée (0, BUG-291). Filtre sur le mois : l'API `periods` filtre `month`/`year`, mais `Commissions.tsx` n'expose que le filtre boulangerie et le statut (`nodeFilter`, `statusFilter`) ; le mois/année n'existe que dans la fenêtre « Générer ». Filtre d'écran absent. |
| « Dans "Commissions CM" section "Situation des Ristournes & Rémunérations" comme dans "Gestion Clientèle"… » | BUG-400 (VÉRIFIÉ par testeur-clients-commissions, dev ≠ testeur) | **déjà `[c]`, à garder** | Backend et écran relus et testés (39 tests verts ci-dessus). Réserve connue : rendu navigateur (360 px) non rejoué, déjà notée dans le texte de la ligne. Rien à changer. |
| « Nouvelle information, les équipes travaillent avec une rotation de 24 heures… » | non couvert par mon périmètre (production/ventes, A) | **laisser `[]`** | Listée « restante » par A ; relève des heures de relève (production), pas de clients/commissions/core. |
| « Dans "Production & Stocks" section "Intrants — Stocks Consommables (§3.2)" La direction doit avoir une vue globale… » | BUG-147, 357 (C) | hors périmètre | À juger par C. |
| Transferts sans demande préalable, Versement visible direction, options de clôture vers Clôture Journalière, modale Stock de départ, Non servi régularisation, clôture automatique | production/trésorerie | hors périmètre (A/C) | Déjà listées à `[]` par A. |

Autres lignes à `[]` de clients, commissions, core, sync, chat, Dashboard, Activities, Users, Nodes, Settings, vitrine : aucune (les 10 lignes `[]` restantes de `remarque.md` sont celles ci-dessus).

Réponse client attendue pour fermer les deux premières lignes : (1) faut-il bien rétablir un frais de carte par boulangerie, contre la décision du 2026-11-14 ? (2) les valeurs §2.3 (taux CM, imprimés, cotisation) doivent-elles passer de `Config` global à un réglage par boulangerie ? (3) filtre mois/année à ajouter dans l'écran Commissions (dev-frontend, ticket à ouvrir par le coordinateur).

## 2. BUG-507

Code : `backend/clients/views.py::ClientViewSet.get_queryset` : `if user.role not in ('FACTURIER', 'LIVREUR'): qs = qs.filter(node=user.node)`. Le livreur voit donc tous les clients (lecture seule : `get_permissions` réserve `create` au facturier et le reste au gérant). CLAUDE.md §5.1 et remarque.md ne citent que le facturier. Statut inchangé (À CLARIFIER).

Question posée : **Q-025** dans `docs/qa/QUESTIONS_CLIENT_SIMPLIFIE.md` (ajoutée en fin, CRLF conservé). Mention ajoutée sur la ligne BUG-507 du registre (édition ciblée, fins de ligne conservées).
