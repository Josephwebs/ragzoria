# Manual de Conexion VPN Corporativa

## Requisitos

Para usar la VPN corporativa el equipo debe estar registrado en inventario TI, tener antivirus activo, sistema operativo actualizado y cliente VPN GlobalProtect version 6 o superior. El usuario debe contar con MFA activo antes de iniciar sesion remota.

## Conexion

El usuario debe abrir GlobalProtect, ingresar el portal vpn.ragzor.local y autenticarse con credenciales corporativas. Luego debe aprobar el segundo factor desde Microsoft Authenticator. Una conexion correcta muestra el estado "Connected" y asigna una IP del rango 10.80.0.0/16.

## Errores frecuentes

Si aparece el error "gateway not reachable", el usuario debe verificar conectividad a internet y reiniciar el cliente VPN. Si aparece "MFA required", debe registrar o reactivar Microsoft Authenticator antes de volver a intentar.

## Escalamiento

Los problemas de VPN que afecten a mas de 10 usuarios o duren mas de 30 minutos se escalan a Infraestructura Nivel 2 con prioridad alta. La Mesa de Ayuda debe adjuntar hora de inicio, proveedor de internet y captura del mensaje de error.

