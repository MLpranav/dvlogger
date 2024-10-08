from setuptools import setup, find_packages

setup(
    name='dvlogger',
    version='0.2.1',
    description='A custom logger with coloured output and uncaught exception logging.',
    packages=find_packages(),
    install_requires=['colorama'],
    author='Pranav Mittal',
    author_email='pranavmittal611@gmail.com',
    url='https://github.com/mlpranav/dvlogger',
    classifiers=[
        'Programming Language :: Python :: 3',
        'Operating System :: OS Independent',
    ],
    python_requires='>=3.8',
)
