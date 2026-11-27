from io import BytesIO
from unittest import TestCase
import zipfile

from studio_build import validate_archive


class StudioDelivery(TestCase):
    def archive(self, *paths):
        data=BytesIO()
        with zipfile.ZipFile(data,"w") as package:
            for path in ("Отчёт.docx","Отчёт.pdf",*paths):
                package.writestr(path,"test payload")
        return zipfile.ZipFile(data)

    def test_one_video_per_task_and_required_resources(self):
        valid=("4.1/Модель.alp","4.1/3d/train.dae","4.1/Демонстрация.mp4")
        with self.archive(*valid) as package:
            validate_archive(package,["4.1"],4)
        with self.archive(*valid,"4.1/Дополнение.mp4") as package:
            with self.assertRaisesRegex(ValueError,"mp4"):
                validate_archive(package,["4.1"],4)
        with self.archive(valid[0],valid[2]) as package:
            with self.assertRaisesRegex(ValueError,"3D"):
                validate_archive(package,["4.1"],4)

    def test_lower_labs_reject_video(self):
        with self.archive("3.1/Модель.alp") as package:
            validate_archive(package,["3.1"],3)
        with self.archive("3.1/Модель.alp","3.1/Демонстрация.mp4") as package:
            with self.assertRaisesRegex(ValueError,"mp4"):
                validate_archive(package,["3.1"],3)
