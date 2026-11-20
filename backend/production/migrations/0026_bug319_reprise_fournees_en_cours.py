from django.db import migrations


def reprise_fournees_en_cours(apps, schema_editor):
    """
    BUG-319 : reprise des fournées par sacs NON clôturées (`auto_track`).
    Leurs lignes DECLARED étaient auto-incrémentées à la livraison (= vendus) et
    `BreadStock.qty_produced` avait reçu les mêmes quantités. Désormais le vendu
    ne sert qu'à la barre d'avancement :
      - `delivered_value_fc` = valeur (prix catalogue) des lignes DECLARED ;
      - `qty_produced` du stock est diminué de ces quantités ;
      - lignes DECLARED supprimées ; totaux et écart remis à 0 (pas d'écart
        avant clôture).
    Les fournées déjà clôturées ne sont pas modifiées (historique).
    """
    ProductionSession = apps.get_model('production', 'ProductionSession')
    ProductionSessionLine = apps.get_model('production', 'ProductionSessionLine')
    BreadStock = apps.get_model('production', 'BreadStock')

    for session in ProductionSession.objects.filter(auto_track=True, is_closed=False):
        lines = list(
            ProductionSessionLine.objects.filter(session=session, source='DECLARED')
            .select_related('bread_price')
        )
        value = 0
        for line in lines:
            value += line.quantity * line.bread_price.unit_price
            stock = BreadStock.objects.filter(node_id=session.node_id, bread_price_id=line.bread_price_id).first()
            if stock is not None:
                stock.qty_produced = stock.qty_produced - line.quantity
                stock.save(update_fields=['qty_produced'])
        ProductionSessionLine.objects.filter(session=session, source='DECLARED').delete()
        remaining_lines = ProductionSessionLine.objects.filter(session=session).select_related('bread_price')
        session.delivered_value_fc = value
        session.total_fc_produced = 0
        session.yield_gap = 0
        session.total_breads = sum(l.quantity for l in remaining_lines)
        session.save(update_fields=['delivered_value_fc', 'total_fc_produced', 'yield_gap', 'total_breads'])


def noop_reverse(apps, schema_editor):
    # Irréversible à l'identique (les quantités vendues par catégorie ne sont
    # pas conservées) : retour arrière = ne rien faire.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('production', '0025_bug319_delivered_value_fc'),
    ]

    operations = [
        migrations.RunPython(reprise_fournees_en_cours, noop_reverse),
    ]
