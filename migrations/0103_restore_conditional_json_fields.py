# pylint: skip-file

import sys

from django.db import migrations

if sys.version_info[0] > 2:
    from django.db.models import JSONField # pylint: disable=no-name-in-module
else:
    from django.contrib.postgres.fields import JSONField

from ..models import install_supports_jsonfield


class Migration(migrations.Migration):

    dependencies = [
        ('passive_data_kit', '0102_databundleprocessingtrace'),
    ]

    if install_supports_jsonfield():
        operations = [
            migrations.SeparateDatabaseAndState(
                database_operations=[
                    migrations.RunSQL(
                        sql=(
                            'ALTER TABLE passive_data_kit_databundle '
                            'ALTER COLUMN properties TYPE jsonb USING properties::jsonb;'
                        ),
                        reverse_sql=(
                            'ALTER TABLE passive_data_kit_databundle '
                            'ALTER COLUMN properties TYPE text USING properties::text;'
                        ),
                    ),
                    migrations.RunSQL(
                        sql=(
                            'ALTER TABLE passive_data_kit_datapoint '
                            'ALTER COLUMN properties TYPE jsonb USING properties::jsonb;'
                        ),
                        reverse_sql=(
                            'ALTER TABLE passive_data_kit_datapoint '
                            'ALTER COLUMN properties TYPE text USING properties::text;'
                        ),
                    ),
                    migrations.RunSQL(
                        sql=(
                            'ALTER TABLE passive_data_kit_datasource '
                            'ALTER COLUMN performance_metadata TYPE jsonb '
                            'USING CASE '
                            "WHEN performance_metadata IS NULL OR BTRIM(performance_metadata) = '' THEN NULL "
                            'ELSE performance_metadata::jsonb '
                            'END;'
                        ),
                        reverse_sql=(
                            'ALTER TABLE passive_data_kit_datasource '
                            'ALTER COLUMN performance_metadata TYPE text '
                            'USING performance_metadata::text;'
                        ),
                    ),
                    migrations.RunSQL(
                        sql=(
                            'ALTER TABLE passive_data_kit_datasourcealert '
                            'ALTER COLUMN alert_details TYPE jsonb USING alert_details::jsonb;'
                        ),
                        reverse_sql=(
                            'ALTER TABLE passive_data_kit_datasourcealert '
                            'ALTER COLUMN alert_details TYPE text USING alert_details::text;'
                        ),
                    ),
                    migrations.RunSQL(
                        sql=(
                            'ALTER TABLE passive_data_kit_reportdestination '
                            'ALTER COLUMN parameters TYPE jsonb USING parameters::jsonb;'
                        ),
                        reverse_sql=(
                            'ALTER TABLE passive_data_kit_reportdestination '
                            'ALTER COLUMN parameters TYPE text USING parameters::text;'
                        ),
                    ),
                    migrations.RunSQL(
                        sql=(
                            'ALTER TABLE passive_data_kit_reportjob '
                            'ALTER COLUMN parameters TYPE jsonb USING parameters::jsonb;'
                        ),
                        reverse_sql=(
                            'ALTER TABLE passive_data_kit_reportjob '
                            'ALTER COLUMN parameters TYPE text USING parameters::text;'
                        ),
                    ),
                    migrations.RunSQL(
                        sql=(
                            'ALTER TABLE passive_data_kit_reportjobbatchrequest '
                            'ALTER COLUMN parameters TYPE jsonb USING parameters::jsonb;'
                        ),
                        reverse_sql=(
                            'ALTER TABLE passive_data_kit_reportjobbatchrequest '
                            'ALTER COLUMN parameters TYPE text USING parameters::text;'
                        ),
                    ),
                ],
                state_operations=[
                    migrations.AlterField(
                        model_name='databundle',
                        name='properties',
                        field=JSONField(),
                    ),
                    migrations.AlterField(
                        model_name='datapoint',
                        name='properties',
                        field=JSONField(),
                    ),
                    migrations.AlterField(
                        model_name='datasource',
                        name='performance_metadata',
                        field=JSONField(blank=True, null=True),
                    ),
                    migrations.AlterField(
                        model_name='datasourcealert',
                        name='alert_details',
                        field=JSONField(),
                    ),
                    migrations.AlterField(
                        model_name='reportdestination',
                        name='parameters',
                        field=JSONField(),
                    ),
                    migrations.AlterField(
                        model_name='reportjob',
                        name='parameters',
                        field=JSONField(),
                    ),
                    migrations.AlterField(
                        model_name='reportjobbatchrequest',
                        name='parameters',
                        field=JSONField(),
                    ),
                ],
            ),
        ]
    else:
        operations = []
