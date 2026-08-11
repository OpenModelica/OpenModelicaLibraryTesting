# The image the OpenModelica repository builds against, see its .CI/common.groovy
FROM docker.openmodelica.org/build-deps:ubuntu-22.04

# -y because a base image that does not assume it turns the build into a prompt,
# and python3-pip because the line below needs it and the base may not carry it.
RUN apt-get update && apt-get install -y libxml2 libxslt1.1 libxml2-dev libxslt1-dev python3-pip
RUN pip3 install matplotlib FMPy psycopg2-binary
