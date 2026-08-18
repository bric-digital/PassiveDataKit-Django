# pylint: disable=line-too-long, no-member

import importlib
import io
import os
import tempfile
import zipfile

import arrow

from django.conf import settings
from django.template import Context, Template

from passive_data_kit.models import DataGeneratorDefinition

def generator_name(identifier): # pylint: disable=unused-argument
    return 'PDK Personal Data Reports'

def compile_report(generator, sources, data_start=None, data_end=None, date_type='created'): # pylint: disable=too-many-locals, too-many-branches, too-many-statements
    now = arrow.get()
    filename = tempfile.gettempdir() + '/pdk_export_' + str(now.timestamp) + str(now.microsecond // 1e6) + '.zip'

    path = os.path.abspath(__file__)

    dir_path = os.path.dirname(path)

    assets_path = dir_path + '/../assets/pdk_personal_data'

    with zipfile.ZipFile(filename, 'w', allowZip64=True) as export_file:
        for source in sources: # pylint: disable=too-many-nested-blocks
            outputs = []

            for definition in DataGeneratorDefinition.objects.exclude(generator_identifier='pdk-personal-data'):
                generator = definition.generator_identifier

                generator_full_name = generator
                output_file = None

                for app in settings.INSTALLED_APPS:
                    if output_file is None:
                        try:
                            generator_module = importlib.import_module('.generators.' + generator.replace('-', '_'), package=app)

                            try:
                                output_file = generator_module.compile_personal_report(generator, [source], data_start=data_start, data_end=data_end, date_type=date_type)
                            except TypeError as exception:
                                print('Verify that ' + app + '.' + generator + ' implements all compile_report arguments!')
                                raise exception

                            try:
                                generator_full_name = generator_module.generator_name(generator)
                            except AttributeError:
                                pass

                        except ImportError:
                            output_file = None
                        except AttributeError:
                            output_file = None

                        if output_file is not None:
                            outputs.append((output_file, generator, generator_full_name))

            source_file = tempfile.gettempdir() + '/pdk_personal_data_' + source + '_' + str(now.timestamp) + str(now.microsecond // 1e6) + '.zip'

            outputs.sort(key=lambda tuple: tuple[2])

            context = Context({
                'outputs': outputs,
                'source': source,
                'settings': settings
            })

            with zipfile.ZipFile(source_file, 'a') as zip_output:
                for output_tuple in outputs:
                    zip_filename = output_tuple[0]

                    with zipfile.ZipFile(zip_filename, 'r') as zip_file:
                        for child_file in zip_file.namelist():
                            with zip_file.open(child_file) as child_stream:
                                if child_file.endswith('.html'):
                                    template = Template(child_stream.read())
                                    zip_output.writestr(child_file, template.render(context))
                                else:
                                    zip_output.writestr(child_file, child_stream.read())

                for folder, subs, files in os.walk(assets_path): # pylint: disable=unused-variable
                    for asset_filename in files:
                        if asset_filename.endswith('.html'):
                            if asset_filename.endswith('index.html'):
                                with io.open(os.path.join(folder, asset_filename), 'r', encoding='utf-8') as src:
                                    template = Template(src.read())

                                    zip_output.writestr(os.path.join(folder.replace(assets_path, ''), asset_filename), template.render(context))
                        else:
                            zip_output.write(os.path.join(folder, asset_filename), os.path.join(folder.replace(assets_path, ''), asset_filename))

            export_file.write(source_file, source + '.zip')

    return filename
