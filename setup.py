from setuptools import setup, find_packages

setup(
    name="vxfreeswitch",
    version="0.1.15",
    url='http://github.com/praekelt/vumi-freeswitch-esl',
    license='BSD',
    description="A Freeswitch eventsocket transport for Vumi.",
    long_description=open('README.rst', 'r').read(),
    author='Praekelt Foundation',
    author_email='dev@praekeltfoundation.org',
    packages=find_packages(),
    include_package_data=True,
    install_requires=[
        'vumi',
        'confmodel>=0.2.0',
        'Twisted>=13.1.0',
        'eventsocket==0.1.5',
    ],
    classifiers=[
        'Development Status :: 4 - Beta',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: BSD License',
        'Operating System :: POSIX',
        'Programming Language :: Python',
        'Topic :: Software Development :: Libraries :: Python Modules',
        'Topic :: System :: Networking',
    ],
)
