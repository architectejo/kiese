import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('clients', '0004_client_client_type'),
        ('core', '0008_config_savings_rate'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='SocialContribution',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('month', models.PositiveSmallIntegerField(verbose_name='Mois')),
                ('year', models.PositiveSmallIntegerField(verbose_name='Année')),
                ('amount', models.DecimalField(decimal_places=2, default='3000.00', max_digits=10, verbose_name='Cotisation (FC)')),
                ('is_paid', models.BooleanField(default=False, verbose_name='Payé')),
                ('paid_at', models.DateTimeField(blank=True, null=True, verbose_name='Date de paiement')),
                ('client', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='social_contributions',
                    to='clients.client',
                    verbose_name='Client',
                )),
                ('node', models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name='social_contributions',
                    to='core.node',
                    verbose_name='Boulangerie',
                )),
            ],
            options={
                'verbose_name': 'Cotisation Sociale',
                'verbose_name_plural': 'Cotisations Sociales',
                'ordering': ['year', 'month', 'client__last_name'],
            },
        ),
        migrations.AddConstraint(
            model_name='socialcontribution',
            constraint=models.UniqueConstraint(fields=['client', 'month', 'year'], name='unique_social_contribution'),
        ),
        migrations.CreateModel(
            name='SocialDistribution',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('year', models.PositiveSmallIntegerField(verbose_name='Année')),
                ('tarif', models.DecimalField(decimal_places=2, default='700.00', max_digits=10, verbose_name='Tarif par indice (FC)')),
                ('is_closed', models.BooleanField(default=False, verbose_name='Clôturée')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('node', models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name='social_distributions',
                    to='core.node',
                    verbose_name='Boulangerie',
                )),
            ],
            options={
                'verbose_name': 'Distribution Sociale Annuelle',
                'verbose_name_plural': 'Distributions Sociales Annuelles',
                'ordering': ['-year', 'node__code'],
            },
        ),
        migrations.AddConstraint(
            model_name='socialdistribution',
            constraint=models.UniqueConstraint(fields=['node', 'year'], name='unique_social_distribution'),
        ),
        migrations.CreateModel(
            name='SocialDistributionLine',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('indice', models.PositiveSmallIntegerField(default=0, verbose_name='Indice (mois cotisés)')),
                ('total_social', models.DecimalField(decimal_places=2, default='0.00', max_digits=10, verbose_name='Total cotisations (FC)')),
                ('remise', models.DecimalField(decimal_places=2, default='0.00', max_digits=10, verbose_name='Remise (indice × tarif)')),
                ('merite', models.DecimalField(decimal_places=2, default='0.00', max_digits=10, verbose_name='Mérite (FC)')),
                ('total_payer', models.DecimalField(decimal_places=2, default='0.00', max_digits=10, verbose_name='Total à recevoir (FC)')),
                ('position', models.CharField(
                    choices=[('present', 'Présent'), ('absent', 'Absent')],
                    default='present', max_length=10, verbose_name='Présence',
                )),
                ('form', models.CharField(
                    choices=[('especes', 'Espèces'), ('colis', 'Colis')],
                    default='especes', max_length=10, verbose_name='Forme de paiement',
                )),
                ('client', models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name='social_distribution_lines',
                    to='clients.client',
                    verbose_name='Client',
                )),
                ('distribution', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='lines',
                    to='clients.socialdistribution',
                    verbose_name='Distribution',
                )),
            ],
            options={
                'verbose_name': 'Ligne Distribution Sociale',
                'verbose_name_plural': 'Lignes Distribution Sociale',
                'ordering': ['client__last_name'],
            },
        ),
        migrations.AddConstraint(
            model_name='socialdistributionline',
            constraint=models.UniqueConstraint(fields=['distribution', 'client'], name='unique_dist_client'),
        ),
    ]
