from django.db import models


class Usuarios(models.Model):
    id_user = models.AutoField(primary_key=True)
    correo = models.CharField(max_length=120 )
    password = models.CharField(max_length=45 )
    fecha_creacion = models.DateTimeField()
    activo = models.CharField(max_length=1 )

    class Meta:
        db_table = 'usuarios'

# Create your models here.
class Personal(models.Model):
    id_p = models.AutoField(primary_key=True)
    run = models.DecimalField(max_digits=8, decimal_places=0 )
    dv = models.CharField(max_length=1, blank=True, null=True )
    nombre = models.CharField(max_length=60 )
    ap_paterno = models.CharField(max_length=60 )
    ap_materno = models.CharField(max_length=60, blank=True, null=True )
    direccion = models.CharField(max_length=100 )
    fono = models.CharField(max_length=45 )
    correo = models.CharField(max_length=100 )
    clave = models.CharField(max_length=45 )
    activo = models.CharField(max_length=1 )
    id_tp = models.ForeignKey('TipoPersonal', models.DO_NOTHING, db_column='id_tp' )

    class Meta:
        db_table = 'personal'
         