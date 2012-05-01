# -*- coding: utf-8 -*-
import os
from setuptools import setup

def read(fname):
    try:
        return open(os.path.join(os.path.dirname(__file__), fname)).read()
    except:
        return ''

setup(
    name='celery-watcher',
    version='0.1',
    description='Celery watcher application',
    author='Roman Imankulov',
    author_email='roman.imankulov@gmail.com',
    url='https://github.com/imankulov/celery-watcher',
    long_description = read('README.rst'),
    license = 'BSD License',
    py_modules=['celery_watcher',],
    scripts=['scripts/celery-watcher',],
    classifiers=(
        'Environment :: Console',
        'Development Status :: 4 - Beta',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: BSD License',
        'Programming Language :: Python',
        'Topic :: Utilities',
    ),
)
