from django.db import migrations, models


def split_names(apps, schema_editor):
    Student = apps.get_model("core", "Student")
    for st in Student.objects.all():
        parts = (st.full_name or "").split()
        st.last_name = parts[0] if parts else ""
        st.first_name = parts[1] if len(parts) > 1 else ""
        st.middle_name = " ".join(parts[2:])
        st.save(update_fields=["last_name", "first_name", "middle_name"])


class Migration(migrations.Migration):
    dependencies = [("core", "0001_initial")]

    operations = [
        migrations.AddField(
            model_name="student", name="last_name",
            field=models.CharField(default="", max_length=80, verbose_name="familiya"), preserve_default=False,
        ),
        migrations.AddField(
            model_name="student", name="first_name",
            field=models.CharField(default="", max_length=80, verbose_name="ism"), preserve_default=False,
        ),
        migrations.AddField(
            model_name="student", name="middle_name",
            field=models.CharField(blank=True, max_length=80, verbose_name="otasining ismi"),
        ),
        migrations.AlterField(
            model_name="student", name="full_name",
            field=models.CharField(editable=False, max_length=245, verbose_name="F.I.Sh."),
        ),
        migrations.AlterField(
            model_name="student", name="student_code",
            field=models.CharField(blank=True, help_text="Ixtiyoriy. Boʻsh qoldirilsa avtomatik beriladi",
                                   max_length=32, unique=True, verbose_name="ID raqami"),
        ),
        migrations.RunPython(split_names, migrations.RunPython.noop),
    ]
