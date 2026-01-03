from setuptools import setup

setup(
    name='mkdocs-plugin-mediacompressor',
    version='0.1',
    description='MkDocs plugin to compress images and videos in the built site',
    packages=['plugin_mediacompressor'],
    include_package_data=True,
    entry_points={
        'mkdocs.plugins': [
            'mediacompressor = plugin_mediacompressor.plugin:MediaCompressorPlugin',
        ],
    },
    install_requires=[
        'mkdocs>=1.0',
        'Pillow>=9.0',
    ],
)