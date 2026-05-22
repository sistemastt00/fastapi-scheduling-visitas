#!/bin/bash
# Túnel ngrok para desarrollo local.
# Expone scheduling-visitas.ngrok.dev → localhost:80
# Configurar Acuity webhook hacia: https://scheduling-visitas.ngrok.dev/acuity
ngrok http --url=scheduling-visitas.ngrok.dev 80
