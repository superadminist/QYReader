import unittest

from novelreader.book_loader import Chapter
from novelreader.directory_titles import directory_labels


class DirectoryTitleTests(unittest.TestCase):
    def test_course_heading_and_continuations_preserve_chapters(self):
        title = "第10课：孩子的问题不在孩子身上，在你老公身上"
        chapters = [Chapter("第 1 节", f"11_{title}\n正文。"), Chapter("第 2 节", "接着上段讲。"), Chapter("第 3 节", "继续讲述。"), Chapter("第 4 节", "第11讲 新的课程\n正文。")]
        before = [chapter.to_dict() for chapter in chapters]
        labels = directory_labels(chapters)
        self.assertEqual([label["displayTitle"] for label in labels], [title, title, title, "第11讲 新的课程"])
        self.assertEqual([label["continuationLabel"] for label in labels], ["", "（续1）", "（续2）", ""])
        self.assertEqual([chapter.to_dict() for chapter in chapters], before)

    def test_existing_titles_and_mixed_directories_win(self):
        chapters = [Chapter("第一章 原题", "第1课 新题\n正文"), Chapter("第 2 节", "另一个开头")]
        self.assertEqual([label["displayTitle"] for label in directory_labels(chapters)], [chapter.title for chapter in chapters])

    def test_excerpt_and_single_heading(self):
        self.assertEqual(directory_labels([Chapter("正文", "Lesson 10: Family\n正文")])[0]["displayTitle"], "Lesson 10: Family")
        chapters = [Chapter("第 1 节", "普通短标题\n正文。"), Chapter("第 2 节", "我们上第十课时讨论问题。后面的句子。")]
        labels = directory_labels(chapters)
        self.assertEqual(labels[0]["displayTitle"], "普通短标题")
        self.assertEqual(labels[1], {"displayTitle": "我们上第十课时讨论问题。", "continuationLabel": ""})

    def test_long_headings_are_retained_and_prose_is_bounded(self):
        title = "第10课：" + "完整的课程名称" * 12
        self.assertEqual(directory_labels([Chapter("第 1 节", title + "\n正文")])[0]["displayTitle"], title)
        self.assertEqual(directory_labels([Chapter("第 1 节", "摘要" * 100)])[0]["displayTitle"], "摘要" * 24 + "…")

    def test_question_heading_is_preserved(self):
        title = "第10课：孩子为什么叛逆？"
        labels = directory_labels([Chapter("第 1 节", "11_" + title + "\n正文。"), Chapter("第 2 节", "后续正文。")])
        self.assertEqual(labels[0]["displayTitle"], title)
        self.assertEqual(labels[1]["continuationLabel"], "（续1）")

    def test_empty_and_long_prose_are_safe(self):
        self.assertEqual(directory_labels([]), [])
        self.assertEqual(directory_labels([Chapter("第 1 节", "")])[0]["displayTitle"], "第 1 节")
        labels = directory_labels([Chapter("第 1 节", "第十课时我们讨论了这些问题。" * 100), Chapter("第 2 节", "接下来的正文。")])
        self.assertEqual(labels[1], {"displayTitle": "接下来的正文。", "continuationLabel": ""})
