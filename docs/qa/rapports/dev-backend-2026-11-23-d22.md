# dev-backend d22 (2026-11-23)
- BUG-890 : CORRIGÉ. Cause : `_cancel_once` (sales/views.py) restituait BP/stock en net mais laissait les factures d'ajustement LIVRÉES. Correction : après passage de la mère en ANNULÉE, les ajustements liés non annulés passent en ANNULÉ (même transaction.atomic, mêmes verrous ; pas de double restitution, le net les incluait déjà).
- Test : test_BUG_890 (marque @expectedFailure retirée dans test_verif_ventes_a6_v6.py, assertions inchangées). test_verif_ventes_a6_v6 + test_bug821_822_824_adjust_d7 : 31 OK.
- Limite : l'ajustement d'une facture EN ATTENTE reste compté dans les résumés tant que la mère n'est pas annulée (comportement inchangé).
- Non lancé : suite complète, makemigrations (aucun changement de schéma).
