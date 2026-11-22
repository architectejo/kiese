# Rapport testeur-tresorerie (Dev C) - 2026-11-22-c2 - cycle 1, nouveaux angles

Branche dev-c. Aucun code applicatif modifie. Pas de commit.

## Tests ajoutes
`backend/treasury/tests/test_cycle1_tresorerie_c.py` : 49 tests, dont 13 `@expectedFailure` (anomalies ci-dessous).
Couverture : cloture (billetage 8 coupures, ecart + / - / 0, ventes cash - depenses, double cloture, date,
transfert en litige, cloture figee, recalcul au versement), rapports par equipe A/B, depenses (montants,
categorie, date, noeud force, roles), epargne, bons de decaissement, livre de caisse (lecture seule pour
ADMIN/DIRECTION/COMPTABLE, hash couvrant node/imputation/source_closure/source_bordereau/is_correction +
chaque champ comptable altere en base, reprise sur collision de parent, rang de chaine), journal, journee complete.
Chaque `@expectedFailure` a ete verifie un a un (decorateur retire dans une copie temporaire) : il echoue pour la bonne raison.

## Tickets ouverts (BUG-810 a BUG-819, `docs/qa/REGISTRE_BUGS.md`)
| Ticket | Gravite | Resume |
|---|---|---|
| BUG-816 | Majeur | DELETE d'un bon de decaissement -> `source_bordereau` NULL (couvert par le hash) -> `chain_valid: false` ; PATCH modifie billets/date sans recalcul |
| BUG-811 | Majeur | cloture creee sans aucun billetage ; billetage/ecart d'une cloture non infirmee modifiable sans trace (b : a confirmer client) |
| BUG-813 | Majeur | depense : date future acceptee ; depense sur un jour de cloture confirmee, net/ecart modifies au versement |
| BUG-817 | Majeur | journal : date future acceptee ; saisie antidatee = solde le plus recent + montant (solde progressif faux) |
| BUG-810 | Mineur | `node: "abc"` dans un POST siege (closures, expenses, reports/generate) -> 500 |
| BUG-812 | Mineur | rapport facturier cree pour une equipe `''` ou `C` |
| BUG-814 | Mineur | epargne : taux 0 remplace par le taux de configuration (`or`) |
| BUG-815 | Mineur | epargne : PATCH de date vers un jour existant -> 500 |
| BUG-818 | Mineur | `date_from`/`date_to` illisibles -> 500 (cashbook, period_summary, final_report) ; `suggested_ca?node=abc` -> 500 |
| BUG-819 | Mineur | deux depenses max le meme jour -> cloture enregistree puis 500 et cloture invisible |
BUG-560 et BUG-563 non rouverts.

## Points conformes (aucun ticket)
- Total billetage = somme quantite x valeur sur les 8 coupures ; valeurs invalides (negatif, decimal, texte, null, > 100000, booleen, liste, 1e9) -> 400.
- Net = ventes cash - depenses locales du noeud seul ; ecart positif, negatif, nul exacts ; champs calcules en lecture seule.
- Double cloture meme jour/noeud refusee (y compris `node` force par un gerant) ; date future refusee.
- Transfert en litige : bloque creation, confirmation et versement ; autre boulangerie non bloquee.
- Cloture confirmee figee (PUT/PATCH/DELETE refuses, gerant ne confirme pas) ; infirmer puis resoumettre recalcule.
- Versement : net negatif = sortie, `VC-<code>-<AAAAMMJJ>`, double versement refuse, recalcul des ventes/depenses arrivees apres la preparation.
- Livre de caisse : POST/PUT/PATCH/DELETE -> 405 pour tous les roles du siege ; gerant/facturier/livreur 403, anonyme 401.
- Hash : l'alteration de chacun des champs comptables (node, imputation, source_closure, source_bordereau, is_correction, piece, libelle, montants, solde, date) est detectee par integrity_check et run_check ne plante pas ; restauration -> chaine valide.
- Collision de parent simulee : reprise automatique, solde correct, rang de chaine monotone ; doublon de `previous_hash` ou de `chain_seq` impossible en base.
- Bons : solde insuffisant et bon a 0 FC refuses sans residu ; solde = precedent + entree - sortie sur 2 boulangeries.
- Journal : PUT/PATCH/DELETE 405, report de mois correct, montants/imputation/date invalides -> 400, `?node=` ignore pour un gerant.
- Epargne : montant = CA x taux arrondi, upsert unique, valeurs hors bornes -> 400, roles et confinement par noeud.
- Roles x boulangerie forgee : gerant d'un autre noeud 404, `node` du corps ou du PATCH ignore, compte sans noeud 403 en ecriture et liste vide.

## Verification
`python manage.py test treasury blockchain` (sans --parallel) : 396 tests, OK (expected failures=13), 456 s.
