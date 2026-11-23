from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("core", "0002_student_name_parts")]

    operations = [
        migrations.AddField(
            model_name="facetemplate",
            name="thumb_encrypted",
            field=models.BinaryField(blank=True, editable=False, null=True, verbose_name="miniatyura (shifrlangan)"),
        ),
    ]
