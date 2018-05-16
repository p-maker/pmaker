======
pmaker
======

pmaker is a toolkit for creating programming contests.

Dependencies:
-------------

(Or skip and it will be installed from pypi)

.. code:: bash

  apt install python3-setuptools{,-scm} python3-jinja2


Install the pmaker:
-------------------

Clone the repo and then

.. code:: bash

  ./setup.py install
  

Tip: You may also use "--user" option for non-privilged install.
Note that this way you will probably need to copy/symlink runnable file from ~/.local/bin to your PATH.

Install the sandbox
--------------------

.. code:: bash

  [sudo] apt install libpcap-dev
  git clone http://github.com/ioi/isolate
  make
  [sudo] make install

For more information please refer to the isolate's official documentation


User guide (short)
-------------------

Following commands are provided

.. code:: bash

  pmaker tests                      # generates all the tests for the problem in current directory
  pmaker invoke <list of solutions> # invokes the specified solutions, use localhost:8128 to see the results
  pmaker invoke @all                # convenience macro
  pmaker view-tests                 # shows all the tests, in browser
  pmaker invokation-list            # to view previous invokations


Example problem
----------------

TODO.

Install completion (optional)
-----------------------------

Completions are provided for bash and located under "completion" folder.

To install bash completion helper copy it to the directory like "/etc/bash_completion.d".
Exact directory name may depend on your Distribution


zsh completion is under development
