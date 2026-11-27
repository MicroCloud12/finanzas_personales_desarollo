"""Planes Gratis / Personal / Pro: cuota mensual de documentos con IA, página de planes y webhook."""
import json
from datetime import timedelta
from unittest.mock import MagicMock, Mock, patch

from mercadopago import SDK as SDK_REAL   # se guarda antes de que los tests lo reemplacen con un mock

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from . import planes
from .models import Suscripcion, UsoIA


def activa(user, plan='personal', periodo='mensual', dias=20, mp_id='pre_1'):
    ahora = timezone.now()
    sus, _ = Suscripcion.objects.update_or_create(usuario=user, defaults=dict(
        estado='activa', plan=plan, periodo=periodo, fecha_inicio=ahora,
        fecha_fin=ahora + timedelta(days=dias), id_suscripcion_mercadopago=mp_id))
    return sus


class CuotaTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('mau', email='mau@test.com', password='x')

    def test_sin_suscripcion_es_gratis_con_10_documentos(self):
        self.assertEqual(planes.plan_de(self.user), 'gratis')
        self.assertEqual(planes.documentos_restantes(self.user), 10)
        planes.registrar_documentos(self.user, 7)
        planes.registrar_documentos(self.user, 7)          # se pasa: el tope se aplica al lanzar, no aquí
        self.assertEqual(planes.documentos_usados(self.user), 14)
        self.assertEqual(planes.documentos_restantes(self.user), 0)
        self.assertFalse(planes.puede_procesar(self.user))
        self.assertIn('Personal', planes.mensaje_sin_cuota(self.user))
        self.assertIn('$99', planes.mensaje_sin_cuota(self.user))

    def test_el_contador_es_por_mes(self):
        hoy = timezone.localdate()
        mes_pasado = (hoy.replace(day=1) - timedelta(days=1))
        planes.registrar_documentos(self.user, 10, hoy=mes_pasado)
        self.assertEqual(planes.documentos_usados(self.user), 0)
        self.assertEqual(UsoIA.objects.filter(usuario=self.user).count(), 1)

    def test_plan_personal_y_pro(self):
        sus = activa(self.user, 'personal')
        self.user.refresh_from_db()
        self.assertEqual(planes.tope_documentos(self.user), 150)
        self.assertFalse(planes.puede_facturar(self.user))
        sus.plan = 'pro'; sus.save()
        self.user = User.objects.get(pk=self.user.pk)
        self.assertEqual(planes.tope_documentos(self.user), 600)
        self.assertTrue(planes.puede_facturar(self.user))
        # vencida: vuelve a Gratis aunque diga 'pro'
        sus.fecha_fin = timezone.now() - timedelta(days=1); sus.save()
        self.user = User.objects.get(pk=self.user.pk)
        self.assertEqual(planes.plan_de(self.user), 'gratis')

    def test_lanzar_grupo_respeta_la_cuota(self):
        from . import tasks
        tarea = Mock(); tarea.name = 'finanzas.tasks.process_single_ticket'
        tarea.app.backend = Mock(get=Mock(return_value=None), set=Mock())
        archivos = [{'id': str(i), 'name': f'{i}.jpg', 'mimeType': 'image/jpeg'} for i in range(12)]
        planes.registrar_documentos(self.user, 7)           # quedan 3 de 10
        with patch.object(tasks.GroupResult, 'restore', return_value=None), \
             patch.object(tasks, 'group') as grupo:
            # group() recibe un generador: hay que consumirlo para que cuente las subtareas
            grupo.side_effect = lambda it: (list(it), Mock(apply_async=Mock(return_value=Mock(id='g1'))))[1]
            r = tasks._lanzar_grupo(tarea, archivos, self.user.id)
            self.assertEqual(r['status'], 'STARTED')
            self.assertEqual(r['total_tasks'], 3)              # solo 3 archivos van a la IA
            self.assertEqual(tarea.s.call_count, 3)
            self.assertEqual(planes.documentos_usados(self.user), 10)
            r = tasks._lanzar_grupo(tarea, archivos, self.user.id)
            self.assertEqual(r['status'], 'SIN_CUOTA')
            self.assertIn('10 documentos', r['message'])
            self.assertEqual(tarea.s.call_count, 3)              # no se mandó nada más

    def test_vistas_muestran_el_contador_y_el_boton_segun_cuota(self):
        self.client.force_login(self.user)
        r = self.client.get(reverse('presupuesto'))
        self.assertContains(r, '0 de 10')
        self.assertContains(r, 'plan Gratis')
        r = self.client.get(reverse('lista_transacciones'))
        self.assertContains(r, 'Auto-Scan')                    # gratis también puede procesar
        planes.registrar_documentos(self.user, 10)
        r = self.client.get(reverse('lista_transacciones'))
        self.assertNotContains(r, 'Auto-Scan')                 # sin cuota, se esconde
        r = self.client.get(reverse('facturacion'))
        self.assertContains(r, 'es del plan Pro')             # facturar es del Pro
        self.assertNotContains(r, reverse('procesamiento_facturacion'))


@patch('finanzas.services.integration_service.mercadopago.SDK')
class PaginaPlanesYWebhookTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('mau', email='mau@test.com', password='x')
        self.client.force_login(self.user)
        self.env = patch.dict('os.environ', {
            'MERCADOPAGO_PLAN_PERSONAL_MENSUAL': 'mp_pm', 'MERCADOPAGO_PLAN_PERSONAL_ANUAL': 'mp_pa',
            'MERCADOPAGO_PLAN_PRO_MENSUAL': 'mp_prm', 'MERCADOPAGO_PLAN_PRO_ANUAL': 'mp_pra'})
        self.env.start(); self.addCleanup(self.env.stop)

    def test_pagina_de_planes(self, SDK):
        r = self.client.get(reverse('gestionar_suscripcion'))
        for texto in ('Gratis', 'Personal', 'Pro', '$99', '$199', '$948', '1,908', '150', '600',
                      'preapproval_plan_id=mp_pm', 'preapproval_plan_id=mp_pra', 'Tu plan'):
            self.assertContains(r, texto)
        self.assertNotContains(r, '$400')
        activa(self.user, 'personal')
        r = self.client.get(reverse('gestionar_suscripcion'))
        self.assertContains(r, 'Cancelar suscripción')
        self.assertContains(r, 'Cambiar a Pro')

    def test_webhook_fija_plan_periodo_y_cancela_el_anterior(self, SDK):
        SDK.return_value = sdk = MagicMock()
        sdk.preapproval.return_value.update.return_value = {"status": 200, "response": {}}
        sus = activa(self.user, 'personal', mp_id='pre_viejo')

        def webhook(sub_id, plan_mp):
            sdk.preapproval.return_value.get.return_value = {"status": 200, "response": {
                "payer_email": "mau@test.com", "status": "authorized", "preapproval_plan_id": plan_mp}}
            payload = {"type": "subscription_preapproval", "data": {"id": sub_id}}
            r = self.client.post(reverse('mercadopago_webhook'), json.dumps(payload), content_type='application/json')
            self.assertEqual(r.status_code, 200)
            sus.refresh_from_db()

        webhook('pre_nuevo', 'mp_pra')                           # cambió a Pro anual
        self.assertEqual((sus.plan, sus.periodo, sus.estado), ('pro', 'anual', 'activa'))
        self.assertEqual(sus.id_suscripcion_mercadopago, 'pre_nuevo')
        self.assertGreater(sus.fecha_fin, timezone.now() + timedelta(days=360))
        sdk.preapproval.return_value.update.assert_called_once_with('pre_viejo', {"status": "cancelled"})
        self.assertEqual(planes.plan_de(User.objects.get(pk=self.user.pk)), 'pro')

        webhook('pre_nuevo', 'desconocido')                      # id que no reconocemos: Personal mensual
        self.assertEqual((sus.plan, sus.periodo), ('personal', 'mensual'))
        sdk.preapproval.return_value.update.assert_called_once()  # mismo id: no cancela nada

    def _preapproval(self, sdk, status='authorized', plan_mp='mp_pm', email='otro@mercadopago.com', **extra):
        sdk.preapproval.return_value.get.return_value = {"status": 200, "response": {
            "payer_email": email, "status": status, "preapproval_plan_id": plan_mp, **extra}}

    def _webhook(self, sub_id):
        payload = {"type": "subscription_preapproval", "data": {"id": sub_id}}
        return self.client.post(reverse('mercadopago_webhook'), json.dumps(payload), content_type='application/json')

    def test_link_lleva_el_id_del_usuario_como_external_reference(self, SDK):
        r = self.client.get(reverse('gestionar_suscripcion'))
        self.assertContains(r, f'preapproval_plan_id=mp_pm&amp;external_reference={self.user.pk}')

    def test_regreso_de_mercado_pago_liga_la_suscripcion_al_usuario_logueado(self, SDK):
        """El correo de Mercado Pago es otro: aun así, al volver con preapproval_id el plan se activa."""
        SDK.return_value = sdk = MagicMock()
        self._preapproval(sdk, plan_mp='mp_prm')
        r = self.client.get(reverse('suscripcion_exitosa') + '?preapproval_id=pre_abc', follow=True)
        self.assertContains(r, 'Tu plan Pro ya está activo')
        sus = Suscripcion.objects.get(usuario=self.user)
        self.assertEqual((sus.estado, sus.plan, sus.periodo, sus.id_suscripcion_mercadopago),
                         ('activa', 'pro', 'mensual', 'pre_abc'))
        # El webhook que llega después (con correo distinto) encuentra la suscripción por el id
        self._preapproval(sdk, status='cancelled', plan_mp='mp_prm')
        self.assertEqual(self._webhook('pre_abc').status_code, 200)
        sus.refresh_from_db()
        self.assertEqual(sus.estado, 'cancelada')

    def test_regreso_sin_parametro_o_con_preapproval_ajeno_no_activa_nada(self, SDK):
        SDK.return_value = sdk = MagicMock()
        r = self.client.get(reverse('suscripcion_exitosa'), follow=True)
        self.assertContains(r, 'se está procesando')
        self.assertEqual(planes.plan_de(self.user), 'gratis')
        # Un preapproval que no es de nuestros planes (p. ej. de otro vendedor) no se liga
        self._preapproval(sdk, plan_mp='plan_de_otro')
        self.client.get(reverse('suscripcion_exitosa') + '?preapproval_id=pre_x', follow=True)
        self.assertEqual(planes.plan_de(User.objects.get(pk=self.user.pk)), 'gratis')
        # Un preapproval que ya es de otro usuario tampoco
        ana = User.objects.create_user('ana', email='ana@test.com', password='x')
        activa(ana, 'personal', mp_id='pre_ana')
        self._preapproval(sdk, plan_mp='mp_pm')
        self.client.get(reverse('suscripcion_exitosa') + '?preapproval_id=pre_ana', follow=True)
        self.assertEqual(planes.plan_de(User.objects.get(pk=self.user.pk)), 'gratis')
        self.assertEqual(Suscripcion.objects.get(usuario=ana).id_suscripcion_mercadopago, 'pre_ana')

    def test_webhook_identifica_por_external_reference_y_si_no_por_correo(self, SDK):
        SDK.return_value = sdk = MagicMock()
        sdk.preapproval.return_value.update.return_value = {"status": 200, "response": {}}
        self._preapproval(sdk, plan_mp='mp_pa', external_reference=str(self.user.pk))   # correo distinto
        self.assertEqual(self._webhook('pre_ref').status_code, 200)
        sus = Suscripcion.objects.get(usuario=self.user)
        self.assertEqual((sus.plan, sus.periodo, sus.id_suscripcion_mercadopago), ('personal', 'anual', 'pre_ref'))
        # Sin external_reference y con correo que nadie tiene: 404 para que Mercado Pago reintente
        self._preapproval(sdk, email='nadie@x.com')
        self.assertEqual(self._webhook('pre_nadie').status_code, 404)
        # Correo conocido aunque con mayúsculas distintas: lo encuentra
        self._preapproval(sdk, email='MAU@test.com', plan_mp='mp_prm')
        self.assertEqual(self._webhook('pre_mail').status_code, 200)
        self.assertEqual(Suscripcion.objects.get(usuario=self.user).plan, 'pro')


class CrearPlanesMPTest(TestCase):
    """El comando crea los 4 planes en Mercado Pago (o reutiliza los que ya existen) e imprime el .env."""

    def _sdk(self, existentes=None):
        sdk = MagicMock(spec=SDK_REAL)   # con spec, usar un método que el SDK real no tiene (p. ej. preapproval_plan) falla aquí
        sdk.plan.return_value.search.return_value = {
            "status": 200, "response": {"results": [{"reason": r, "id": i} for r, i in (existentes or {}).items()]}}
        sdk.plan.return_value.create.side_effect = lambda cuerpo: {
            "status": 201, "response": {"id": "id_" + cuerpo["reason"].split('(')[1][:3] + cuerpo["reason"].split()[2][:3]}}
        return sdk

    @patch.dict('os.environ', {'MERCADOPAGO_ACCESS_TOKEN': 'APP_USR-x'})
    @patch('finanzas.management.commands.crear_planes_mp.mercadopago.SDK')
    def test_crea_los_cuatro_planes(self, SDK):
        from io import StringIO
        from django.core.management import call_command
        SDK.return_value = sdk = self._sdk()
        salida = StringIO()
        call_command('crear_planes_mp', '--dominio', 'prismavault.mx', stdout=salida)
        cuerpos = [c.args[0] for c in sdk.plan.return_value.create.call_args_list]
        self.assertEqual(len(cuerpos), 4)
        por_razon = {c['reason']: c for c in cuerpos}
        p = por_razon['Prisma Vault Personal (mensual)']['auto_recurring']
        self.assertEqual((p['transaction_amount'], p['frequency'], p['frequency_type'], p['currency_id']), (99, 1, 'months', 'MXN'))
        a = por_razon['Prisma Vault Pro (anual)']['auto_recurring']
        self.assertEqual((a['transaction_amount'], a['frequency']), (1908, 12))
        self.assertEqual(cuerpos[0]['back_url'], 'https://prismavault.mx/suscripcion/exitosa/')
        texto = salida.getvalue()
        for variable in ('MERCADOPAGO_PLAN_PERSONAL_MENSUAL=', 'MERCADOPAGO_PLAN_PERSONAL_ANUAL=',
                         'MERCADOPAGO_PLAN_PRO_MENSUAL=', 'MERCADOPAGO_PLAN_PRO_ANUAL='):
            self.assertIn(variable, texto)
        self.assertIn('https://prismavault.mx/suscripcion/webhook/', texto)

    @patch.dict('os.environ', {'MERCADOPAGO_ACCESS_TOKEN': 'TEST-x'})
    @patch('finanzas.management.commands.crear_planes_mp.mercadopago.SDK')
    def test_reutiliza_los_que_ya_existen_y_avisa_si_el_token_es_de_pruebas(self, SDK):
        from io import StringIO
        from django.core.management import call_command
        SDK.return_value = sdk = self._sdk({'Prisma Vault Personal (mensual)': 'viejo_1', 'Prisma Vault Pro (anual)': 'viejo_2'})
        salida = StringIO()
        call_command('crear_planes_mp', '--dominio', 'prismavault.mx', stdout=salida)
        self.assertEqual(sdk.plan.return_value.create.call_count, 2)   # solo los que faltaban
        self.assertIn('MERCADOPAGO_PLAN_PERSONAL_MENSUAL=viejo_1', salida.getvalue())
        self.assertIn('MERCADOPAGO_PLAN_PRO_ANUAL=viejo_2', salida.getvalue())
        self.assertIn('PRUEBAS', salida.getvalue())

    @patch.dict('os.environ', {'MERCADOPAGO_ACCESS_TOKEN': 'APP_USR-x'})
    @patch('finanzas.management.commands.crear_planes_mp.mercadopago.SDK')
    def test_solo_mostrar_no_crea_nada(self, SDK):
        from io import StringIO
        from django.core.management import call_command
        salida = StringIO()
        call_command('crear_planes_mp', '--dominio', 'prismavault.mx', '--solo-mostrar', stdout=salida)
        SDK.assert_not_called()
        self.assertIn('$99 MXN cada 1 mes', salida.getvalue())
        self.assertIn('$1908 MXN cada 12 mes', salida.getvalue())
