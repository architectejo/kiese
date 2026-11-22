# Rapport testeur-tresorerie, cycle 2 partie C (Dev C), 2026-11-22

Branche dev-c (3eb99d1). Tests : `backend/treasury/tests/test_cycle2_tresorerie_c.py` (53 tests : 30 verts, 23 `@expectedFailure`).
`python manage.py test treasury blockchain` (sans parallele) : 468 tests, OK (1 skip, 24 echecs attendus dont BUG-811 b). Code applicatif non modifie.

## 1. Verifications

| Ticket | Verdict | Angles attaques |
|---|---|---|
| BUG-560 | VERIFIE | balayage `?node=` (11 valeurs hostiles) sur 13 routes treasury + 3 blockchain ; autres filtres (category, date, is_validated, ordering, month/year chiffres arabes) : aucun 500 ; double rapport par un siege (equipe du corps forgee) : 400 |
| BUG-561 | VERIFIE | corps `[]`, `[1]`, `1`, `"x"`, `null`, `true`, `text/plain`, `node` liste/objet : jamais 500 |
| BUG-563 | VERIFIE | SIEGE exclu, `count` = somme des compteurs, noeud inactif reel conserve, `?node=SIEGE` 403, gerant limite a son noeud |
| BUG-811 | (a) VERIFIE ; (b) reste A CLARIFIER | billets negatifs/`null` toujours 400 ; observation : comptage Direction sans coupure accepte (pas de ticket) |
| BUG-812 | VERIFIE (creation) | equipe du corps ignoree. Le PATCH d'equipe `Z` sur un rapport passe : BUG-830 |
| BUG-813 | VERIFIE (depenses) | corps `node` siege, deplacement vers/hors d'un jour confirme, jour infirme ouvert + resoumission + versement coherents, suppression de cloture confirmee 403. Le gel ne couvre pas les rapports : BUG-830 |
| BUG-814 | VERIFIE | taux 0 et 1 honores, 1,0001 / -0,1 / null / NaN / 1e400 / listes : jamais 500, PATCH taux 0 recalcule, upsert idempotent |
| BUG-816 | VERIFIE | matrice PUT/PATCH/DELETE/POST sur bons, livre, integrity_check, journal, snapshots : 405 pour le siege, 401/403 sinon ; etat et chaine intacts. Alertes de falsification : BUG-832 |
| BUG-817 | VERIFIE | 14 ecritures en ordre aleatoire sur 2 noeuds : `running_balance` et `month_carried` egaux au recalcul de zero ; meme jour ; rapport mensuel ; chaine de hash intacte apres antidatage |
| BUG-819 | VERIFIE (portee decrite) | totaux entrees/depenses : 400. Variantes hors portee : BUG-834 |
| BUG-810 | ROUVERT | `node: true` ou `1.5` dans le corps (cloture, depense, rapport, journal, epargne) : 201 sur le noeud de pk 1 |
| BUG-815 | ROUVERT | PATCH `node` d'une epargne (siege) vers un jour existant : 500 ; PATCH `date` d'une cloture vers le jour d'une autre : 500 |
| BUG-818 | ROUVERT | `reports/generate/` `{"date": "2026-02-30"}` : 500 (`parse_date` leve `ValueError`) ; le reste du balayage est propre |

## 2. Nouveaux tickets (BUG-830 a 839, tous OUVERT)

- BUG-830 (Majeur) rapport non valide : PATCH date sur un jour confirme, DELETE, equipe `Z`.
- BUG-831 (Mineur) dates futures : epargne et bon de decaissement.
- BUG-832 (Majeur) `TamperAlertViewSet` en ecriture libre (DELETE 204, POST 500).
- BUG-833 (Mineur) `journal/monthly_report/` siege sans noeud : totaux de tous les noeuds, solde d'un seul.
- BUG-834 (Mineur) depassement DecimalField : ecart de cloture, solde cumule du livre.
- BUG-835 (Majeur) comptage Direction : solde theorique faux si versements hors ordre chronologique.
- BUG-836 (Mineur) `run_check` : noeud etranger accuse (`?node=`), alertes dupliquees, `global_status` intact avec 0 verification.
- BUG-837 (Mineur) `log_activity` absent : creation de cloture, suppression de depense, `run_check`, resolution d'alerte.
- BUG-838 (Mineur) N+1 : depenses (categorie), alertes, snapshots.
- BUG-839 (Majeur) versement : double versement sur lecture perimee, cloture confirmee modifiee puis ecriture echouee, montant confirme != inscrit, bon orphelin.

Verifie sans anomalie : deux endpoints d'integrite (meme verdict propre, altere, queue amputee), chaine apres 30 ecritures et bon antidate, double push refuse en sequence, roles validate/reject/push, champs calcules non forgeables sur creation/PATCH de cloture, requetes constantes sur clotures, rapports, livre, journal, epargne, bons, versements.

## 3. Hors ticket (a clarifier)
- BUG-811 (b) toujours en attente du client.
- Comptage Direction sans aucune coupure accepte (ecart = -solde) : meme question que BUG-811, niveau 3.
- Les 3 rouverts et BUG-830 a 839 sont a corriger par dev-backend ; je repasserai ensuite.
