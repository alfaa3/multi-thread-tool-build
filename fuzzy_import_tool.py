#!/usr/bin/env python3
"""模糊导入工具 - 从剪贴板快速填充用户名和密码 + xjyxjyw.com 登录"""

import sys
import re
import time
import os
from urllib.parse import quote

import requests
import json

from bs4 import BeautifulSoup

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QLabel, QLineEdit, QPushButton, QTableWidget, QTableWidgetItem,
    QHeaderView, QGroupBox, QPlainTextEdit, QMessageBox, QTextEdit
)
from PyQt5.QtCore import Qt, QTimer, QObject, pyqtSignal, QThread, QRect, QPoint, QSize
from PyQt5.QtWidgets import QLayout



# ====== 超级鹰配置 ======
SUPER_EAGLE_USER = "alfaa3"
SUPER_EAGLE_PASS = "123456"
SUPER_EAGLE_SOFTID = "976381"


# ====== Flow Layout（自动换行布局） ======
class FlowLayout(QLayout):
    """水平流式布局，放不下自动换行"""
    def __init__(self, parent=None, margin=0, spacing=4):
        super().__init__(parent)
        self.setContentsMargins(margin, margin, margin, margin)
        self.setSpacing(spacing)
        self._item_list = []

    def addItem(self, item):
        self._item_list.append(item)

    def count(self):
        return len(self._item_list)

    def itemAt(self, index):
        return self._item_list[index] if 0 <= index < len(self._item_list) else None

    def takeAt(self, index):
        return self._item_list.pop(index) if 0 <= index < len(self._item_list) else None

    def removeWidget(self, widget):
        for item in self._item_list[:]:
            if item.widget() == widget:
                self._item_list.remove(item)
                break

    def expandingDirections(self):
        return Qt.Orientations(Qt.Orientation(0))

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._do_layout(QRect(0, 0, width, 0), True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do_layout(rect, False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for item in self._item_list:
            size = size.expandedTo(item.minimumSize())
        m = self.contentsMargins()
        size += QSize(m.left() + m.right(), m.top() + m.bottom())
        return size

    def _do_layout(self, rect, test_only):
        m = self.contentsMargins()
        x = rect.x() + m.left()
        y = rect.y() + m.top()
        line_height = 0
        spacing = self.spacing()

        for item in self._item_list:
            hint = item.sizeHint()
            next_x = x + hint.width() + spacing
            if next_x - spacing > rect.right() - m.right() and line_height > 0:
                x = rect.x() + m.left()
                y += line_height + spacing
                next_x = x + hint.width() + spacing
                line_height = 0
            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x = next_x
            line_height = max(line_height, hint.height())

        return (y + line_height + m.bottom()) - rect.y()
class ClipboardWatcher:
    """监控剪贴板内容变化"""

    def __init__(self, on_change_callback):
        self._last_text = ""
        self._callback = on_change_callback

    def check(self):
        text = QApplication.clipboard().text().strip()
        if text and text != self._last_text:
            self._last_text = text
            self._callback(text)
            return True
        return False


# ====== 登录工作线程（信号桥模式） ======
class LoginSignals(QObject):
    started = pyqtSignal()
    progress = pyqtSignal(str)
    finished = pyqtSignal(str, str, str, dict, str)  # status, detail, elapsed, cookies_dict, ic_card


class LoginWorker(QObject):
    """在后台线程执行登录，不阻塞GUI"""

    def __init__(self, account, password):
        super().__init__()
        self.account = account
        self.password = password
        self.cancel = False
        self.signals = LoginSignals()

    def run(self):
        self.signals.started.emit()

        sess = requests.Session()
        sess.headers.update({
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36"
        })
        t0 = time.time()

        # 1. 获取 JSESSIONID
        try:
            sess.get("https://www.xjyxjyw.com/mlogin.jsp", timeout=15)
        except Exception as e:
            self.signals.finished.emit("失败", f"连接失败: {e}", "", {}, "")
            return
        if self.cancel:
            self.signals.finished.emit("已取消", "", "", {}, "")
            return

        # 2. 验证码
        try:
            ts = quote(time.strftime("%a %b %d %H:%M:%S", time.localtime()))
            cap = sess.get(f"https://www.xjyxjyw.com/image.jsp?date={ts}", timeout=15)
        except Exception as e:
            self.signals.finished.emit("失败", f"验证码获取失败: {e}", "", {}, "")
            return
        if self.cancel:
            self.signals.finished.emit("已取消", "", "", {}, "")
            return

        self.signals.progress.emit("正在识别验证码...")

        # 3. 超级鹰识别
        code = self._ocr(cap.content)
        if not code:
            self.signals.finished.emit("失败", "验证码识别失败", f"{time.time()-t0:.1f}s", {}, "")
            return
        if code.startswith("__ERR:"):
            self.signals.finished.emit("失败", f"超级鹰:{code[6:]}", f"{time.time()-t0:.1f}s", {}, "")
            return
        if len(code) != 4:
            self.signals.finished.emit("失败", f"验证码位数不对({code})", f"{time.time()-t0:.1f}s", {}, "")
            return

        self.signals.progress.emit(f"验证码识别成功: {code}，正在登录...")

        # 4. 登录
        try:
            r = sess.post("https://www.xjyxjyw.com/member_login.do",
                          data={"member.loginname": self.account,
                                "member.pwd": self.password,
                                "ValidateCode": code},
                          timeout=15, allow_redirects=False)
        except Exception as e:
            self.signals.finished.emit("失败", f"登录请求失败: {e}", "", {}, "")
            return
        if self.cancel:
            self.signals.finished.emit("已取消", "", "", {}, "")
            return

        elapsed = f"{time.time()-t0:.1f}s"

        # 5. 判断登录结果
        if r.status_code not in (302, 303, 307):
            html = r.text
            if "验证码" in html and "错误" in html:
                self.signals.finished.emit("失败", "验证码错误", elapsed, {}, "")
            elif "密码" in html and "错误" in html:
                self.signals.finished.emit("失败", "密码错误", elapsed, {}, "")
            elif "没有您的信息" in html:
                self.signals.finished.emit("失败", "无此账号", elapsed, {}, "")
            else:
                self.signals.finished.emit("失败", "登录失败", elapsed, {}, "")
            return

        # 登录成功，跟随重定向
        try:
            sess.get("https://www.xjyxjyw.com/member_login.do", timeout=15)
        except Exception:
            pass

        # 6. 读取用户信息
        try:
            acct_resp = sess.get("https://www.xjyxjyw.com/member/member_account.do", timeout=15)
            html = acct_resp.text

            # IC卡
            ic_match = re.search(
                r'name=["\']member\.icCard["\'][^>]*value=["\']([^"\']*)["\']',
                html
            )
            ic_card = ic_match.group(1).strip() if ic_match else ""

            # 姓名
            name_match = re.search(
                r'name=["\']member\.(?:name|realName)["\'][^>]*value=["\']([^"\']*)["\']',
                html
            )
            name = name_match.group(1).strip() if name_match else ""

            # 单位
            unit_match = re.search(
                r'name=["\']member\.(?:selfFillUnit|workUnit|company|unit)["\'][^>]*value=["\']([^"\']*)["\']',
                html
            )
            unit = unit_match.group(1).strip() if unit_match else ""

            # 专业
            spec_match = re.search(
                r'name=["\']member\.(?:specialty|major|profession)["\'][^>]*value=["\']([^"\']*)["\']',
                html
            )
            specialty = spec_match.group(1).strip() if spec_match else ""

        except Exception:
            ic_card = ""
            name = ""
            unit = ""
            specialty = ""

        if not ic_card:
            self.signals.finished.emit("失败", "未绑定IC卡", f"{time.time()-t0:.1f}s", {}, "")
            return

        # 7. 组装详情
        detail = f"IC卡: {ic_card}"
        if name:
            detail += f" | 姓名: {name}"
        if unit:
            detail += f" | 单位: {unit}"
        if specialty:
            detail += f" | 专业: {specialty}"

        self.signals.finished.emit("成功", detail, f"{time.time()-t0:.1f}s",
                                   requests.utils.dict_from_cookiejar(sess.cookies), ic_card)

    def _ocr(self, img_data):
        """超级鹰"""
        if SUPER_EAGLE_USER == "your_username":
            return ""
        # 保存图片用于调试
        import tempfile
        debug_path = os.path.join(tempfile.gettempdir(), "captcha_last.jpg")
        with open(debug_path, "wb") as f:
            f.write(img_data)
        r = requests.post("https://upload.chaojiying.net/Upload/Processing.php",
                          data={"user": SUPER_EAGLE_USER, "pass": SUPER_EAGLE_PASS,
                                "softid": SUPER_EAGLE_SOFTID, "codetype": "4004"},
                          files={"userfile": ("c.jpg", img_data, "image/jpeg")}, timeout=15)
        try:
            j = r.json()
            if j.get("err_no") == 0:
                return j.get("pic_str", "")
            else:
                # 返回错误码，让调用方显示具体原因
                return f"__ERR:{j.get('err_no')}:{j.get('err_str','')}"
        except Exception as e:
            return f"__ERR:PARSE:{e}"


# ====== 学习工作线程 ======
class StudySignals(QObject):
    started = pyqtSignal()
    progress = pyqtSignal(str)
    course_start = pyqtSignal(str, str)   # course_name, total_videos
    video_done = pyqtSignal(str, str, str)  # video_title, status, detail
    finished = pyqtSignal(bool, str)  # success, summary


class StudyWorker(QObject):
    """在后台线程执行学习任务"""

    BASE_URL = "https://www.xjyxjyw.com"

    def __init__(self, cookies, courses):
        super().__init__()
        self.cookies = cookies
        self.courses = courses  # [{"name": ..., "id": ...}, ...]
        self.cancel = False
        self.signals = StudySignals()

    def run(self):
        self.signals.started.emit()
        sess = requests.Session()
        sess.headers.update({
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36"
        })
        for k, v in self.cookies.items():
            sess.cookies.set(k, v)

        total = len(self.courses)
        success_count = 0

        for idx, course in enumerate(self.courses):
            if self.cancel:
                self.signals.finished.emit(False, "已取消")
                return

            course_id = course["id"]
            course_name = course["name"]
            self.signals.progress.emit(f"[{idx + 1}/{total}] {course_name}")

            # 1. 获取视频列表
            videos = self._get_video_list(sess, course_id)
            if videos is None:
                self.signals.progress.emit(f"  ❌ {course_name}: 获取视频列表失败")
                continue

            if not videos:
                self.signals.progress.emit(f"  ⏭ {course_name}: 无待学习视频")
                success_count += 1
                continue

            self.signals.course_start.emit(course_name, str(len(videos)))
            all_ok = True

            for v in videos:
                if self.cancel:
                    self.signals.finished.emit(False, "已取消")
                    return

                title = v["video_title"]
                full_ware_id = v["full_ware_id"]
                status = v["status"]
                ware_id = v["ware_id"]

                # 未学习 → 先学
                if "未学习" in status:
                    self.signals.progress.emit(f"  📖 学习: {title}")
                    ok = self._learn_video(sess, full_ware_id)
                    if not ok:
                        self.signals.video_done.emit(title, "失败", "学习请求失败")
                        all_ok = False
                        continue
                    self.signals.video_done.emit(title, "已学习", "")
                    time.sleep(1)

                # 考试
                self.signals.progress.emit(f"  📝 考试: {title}")
                exam_ok = self._do_exam(sess, course_id, ware_id)
                if exam_ok:
                    self.signals.video_done.emit(title, "通过考试", "")
                else:
                    self.signals.video_done.emit(title, "考试失败", "")
                    all_ok = False

                time.sleep(1)

            if all_ok:
                success_count += 1
            time.sleep(2)

        summary = f"完成 {success_count}/{total} 门课程"
        self.signals.finished.emit(success_count == total, summary)

    def _get_video_list(self, sess, course_id):
        """获取课程下的视频列表"""
        try:
            url = f"{self.BASE_URL}/member/cw_info.do?id={course_id}"
            r = sess.get(url, timeout=15)
            html = r.text

            if "所有参加培训人员需要完善自己的个人信息" in html:
                return None
            if "此课程已下线" in html:
                return []

            soup = BeautifulSoup(html, "html.parser")
            videos = []
            seen_ids = set()

            for li in soup.find_all("li"):
                h3 = li.find("h3", class_="discuss-title")
                if not h3:
                    continue

                link_tag = h3.find("a", href=re.compile(r"courseWare_play\.do"))
                if not link_tag:
                    continue

                href = link_tag["href"]
                match = re.search(r"courseWare\.id=(\d+)", href)
                if not match:
                    continue

                full_ware_id = match.group(1)
                if full_ware_id in seen_ids:
                    continue
                seen_ids.add(full_ware_id)

                video_title = link_tag.get_text(strip=True)
                if video_title in ("点击学习", "继续学习"):
                    continue

                status_span = li.find("span", class_="discuss-time")
                status_text = status_span.get_text(strip=True) if status_span else ""

                if "通过考试" in status_text:
                    continue

                ware_id = full_ware_id
                if ware_id.startswith(course_id):
                    ware_id = ware_id[len(course_id):]

                videos.append({
                    "ware_id": ware_id,
                    "full_ware_id": full_ware_id,
                    "video_title": video_title,
                    "status": status_text,
                })

            return videos
        except Exception as e:
            return None

    def _learn_video(self, sess, full_ware_id):
        """完成视频学习"""
        try:
            ts = int(time.time() * 1000)
            url = f"{self.BASE_URL}/member/courseWare_playEnd.do?id={full_ware_id}&_={ts}"
            sess.get(url, headers={
                "X-Requested-With": "XMLHttpRequest",
                "Referer": f"{self.BASE_URL}/member/courseWare_play.do?courseWare.id={full_ware_id}&flag=-1",
            }, timeout=15)
            return True
        except Exception:
            return False

    def _do_exam(self, sess, course_id, ware_id):
        """暴力枚举答题"""
        try:
            # 1. 获取题目
            exam_url = f"{self.BASE_URL}/member/exam_quelist.do?flag=0&ncmeQuestion.courseId={course_id}&ncmeQuestion.coursewareId={ware_id}"
            r = sess.get(exam_url, timeout=15)
            soup = BeautifulSoup(r.text, "html.parser")

            inputs = soup.find_all("input", attrs={"type": "radio"})
            question_ids = []
            for inp in inputs:
                name = inp.get("name")
                if name and name not in question_ids:
                    question_ids.append(name)

            if not question_ids:
                return True

            # 2. 初始化答案
            options = ["A", "B", "C", "D", "E", "F"]
            current_answers = {qid: "A" for qid in question_ids}
            no_error_count = 0

            while True:
                # 提交答案
                answer_data = [
                    {"name": qid, "value": current_answers[qid]}
                    for qid in question_ids
                ]
                post_data = {
                    "flag": "0",
                    "ncmeQuestion.data": json.dumps(answer_data),
                    "ncmeQuestion.courseId": course_id,
                    "ncmeQuestion.coursewareId": ware_id,
                }

                result_r = sess.post(f"{self.BASE_URL}/member/exam_result.do",
                                     data=post_data, timeout=15)
                result_html = result_r.text

                # 检查是否通过
                if "本课件通过考试" in result_html or "本课程通过考试" in result_html or "申请学分" in result_html:
                    return True

                # 解析错题
                result_soup = BeautifulSoup(result_html, "html.parser")
                result_paras = result_soup.find_all("p", class_="h4")
                valid_results = [p for p in result_paras if "您的回答" in p.get_text()]

                if not valid_results:
                    continue

                has_errors = False
                for idx, p_tag in enumerate(valid_results):
                    if idx >= len(question_ids):
                        break
                    text = p_tag.get_text()
                    qid = question_ids[idx]
                    if "您的回答：错误" in text:
                        has_errors = True
                        curr_idx = options.index(current_answers[qid])
                        next_idx = (curr_idx + 1) % len(options)
                        current_answers[qid] = options[next_idx]

                if has_errors:
                    no_error_count = 0
                else:
                    no_error_count += 1
                    if no_error_count >= 3:
                        return False
                    first_qid = question_ids[0]
                    curr_idx = options.index(current_answers[first_qid])
                    next_idx = (curr_idx + 1) % len(options)
                    current_answers[first_qid] = options[next_idx]

        except Exception:
            return False


# ====== 学分申请工作线程 ======
class CreditSignals(QObject):
    started = pyqtSignal()
    progress = pyqtSignal(str)
    success = pyqtSignal(str)  # detail
    failed = pyqtSignal(str)   # reason
    show_qr = pyqtSignal(object, str, str, str)  # cookies_dict, out_trade_no, course_id, qr_url
    finished = pyqtSignal()


class CreditWorker(QObject):
    """后台线程：为指定课程申请学分（含自动购卡）"""

    BASE_URL = "https://www.xjyxjyw.com"

    def __init__(self, cookies, course_id, course_name):
        super().__init__()
        self.cookies = cookies
        self.course_id = course_id
        self.course_name = course_name
        self.cancel = False
        self.signals = CreditSignals()

    def _make_session(self):
        sess = requests.Session()
        sess.headers.update({
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36"
        })
        for k, v in self.cookies.items():
            sess.cookies.set(k, v)
        return sess

    def run(self):
        self.signals.started.emit()
        self.signals.progress.emit(f"申请学分: {self.course_name}")
        sess = self._make_session()
        self._apply_with_session(sess)

    def _apply_with_session(self, sess):
        """用已有 session 申请学分"""
        # 1. 获取申请页面
        try:
            r = sess.get(f"{self.BASE_URL}/member/apply_apply.do?course_id={self.course_id}", timeout=15)
        except Exception as e:
            self.signals.failed.emit(f"请求失败: {e}")
            self.signals.finished.emit()
            return

        # 2. 解析卡信息
        card_no, card_pwd, score = self._parse_card_info(r.text)
        if card_no and card_pwd and score > 0:
            self._do_apply(sess, card_no, card_pwd)
            return

        # 3. 无可用卡 → 自动购卡
        self.signals.progress.emit("未找到可用学习卡，开始购卡流程...")
        self._buy_card(sess)

    def _parse_card_info(self, html):
        """从申请页面解析卡号、密码、可用分值"""
        card_no = ""
        card_pwd = ""
        score = 0
        for tr in re.findall(r'<tr[^>]*>(.*?)</tr>', html, re.DOTALL):
            if "使用此卡申请" not in tr:
                continue
            tds = re.findall(r'<td[^>]*>(.*?)</td>', tr, re.DOTALL)
            if len(tds) < 5:
                continue
            # 提取数字串
            nums = re.findall(r'\d+', tr)
            cn, cp = "", ""
            for n in nums:
                if len(n) >= 10 and not cn:
                    cn = n
                elif len(n) >= 4 and cn and not cp:
                    cp = n
            if not cn or not cp:
                continue
            try:
                s = float(re.sub(r'[^\d.]', '', re.sub(r'<[^>]+>', '', tds[4])))
            except ValueError:
                s = 0
            # 取分值最高的卡
            if s > score:
                card_no, card_pwd, score = cn, cp, s
        return card_no, card_pwd, score

    def _do_apply(self, sess, card_no, card_pwd):
        """用指定卡申请学分"""
        try:
            url = (f"{self.BASE_URL}/member/apply_applyCard.do"
                   f"?courseLog.cid={self.course_id}"
                   f"&cardNo={card_no}&cardPasswd={card_pwd}")
            resp = sess.get(url, timeout=15)
            if "申请成功" in resp.text:
                self.signals.success.emit(f"申请成功")
            else:
                self.signals.failed.emit(f"申请失败")
        except Exception as e:
            self.signals.failed.emit(f"请求异常: {e}")
        self.signals.finished.emit()

    def _buy_card(self, sess):
        """购卡流程：获取 product_id → 生成微信支付 → 显示二维码"""
        # 1. 获取 product_id
        try:
            r = sess.get(f"{self.BASE_URL}/member/myCard_card.do?ids={self.course_id}", timeout=15)
            html = r.text
            # 调试保存
            import tempfile
            dbg = os.path.join(tempfile.gettempdir(), "mycard_card.html")
            with open(dbg, "w", encoding="utf-8") as f:
                f.write(html)
            # 多种方式查找 product_id
            product_id = ""
            for pat in [
                r'product_id["\']?\s*[:=]\s*["\']?(\d+)',
                r'productId["\']?\s*[:=]\s*["\']?(\d+)',
                r'name=["\']product_id["\'][^>]*value=["\'](\d+)',
                r'name=["\']productId["\'][^>]*value=["\'](\d+)',
                r'product_id["\']?\s*["\']?(\d+)',
            ]:
                m = re.search(pat, html)
                if m:
                    product_id = m.group(1)
                    break
            if not product_id:
                self.signals.failed.emit(f"未找到商品信息，页面已保存到 {dbg}")
                self.signals.finished.emit()
                return
        except Exception as e:
            self.signals.failed.emit(f"获取商品信息失败: {e}")
            self.signals.finished.emit()
            return

        # 2. 访问购卡页
        try:
            buy_url = (f"{self.BASE_URL}/member/myCard_buycard.do"
                       f"?product_id={product_id}&ids={self.course_id}"
                       f"&paycode=02&product_quantity=1")
            buy_resp = sess.get(buy_url, timeout=15)
        except Exception as e:
            self.signals.failed.emit(f"购卡页请求失败: {e}")
            self.signals.finished.emit()
            return

        # 3. 解析表单字段
        form_fields = {}
        for name_field in ("WIDbody", "WIDshow_url", "out_trade_no", "WIDsubject", "WIDtotal_fee"):
            m = re.search(r'name=["\']' + name_field + r'["\'][^>]*value=["\']([^"\']+)["\']', buy_resp.text)
            if m:
                form_fields[name_field] = m.group(1)
            else:
                m = re.search(r'name=["\']' + name_field + r'["\'](?:[^>]*>)\s*([^<\s]+)', buy_resp.text)
                if m:
                    form_fields[name_field] = m.group(1)

        if "out_trade_no" not in form_fields:
            self.signals.failed.emit("未找到订单号")
            self.signals.finished.emit()
            return

        out_trade_no = form_fields["out_trade_no"]

        # 4. 提交获取二维码页面
        try:
            post_data = {
                "WIDbody": form_fields.get("WIDbody", ""),
                "WIDshow_url": form_fields.get("WIDshow_url", ""),
                "out_trade_no": out_trade_no,
                "WIDsubject": form_fields.get("WIDsubject", "") + "&WIDsubject=1",
                "WIDtotal_fee": form_fields.get("WIDtotal_fee", "") + "&WIDtotal_fee=微信",
            }
            wx_resp = sess.post(f"{self.BASE_URL}/member/myCard_wxPay.do",
                                data=post_data, timeout=15,
                                headers={"Referer": buy_url,
                                         "Content-Type": "application/x-www-form-urlencoded"})
        except Exception as e:
            self.signals.failed.emit(f"支付请求失败: {e}")
            self.signals.finished.emit()
            return

        # 5. 提取二维码 URL
        qr_url = ""
        for pat in [r'var\s+url\s*=\s*"([^"]+)"', r"var\s+url\s*=\s*'([^']+)'"]:
            m = re.search(pat, wx_resp.text)
            if m:
                qr_url = m.group(1)
                break

        if not qr_url:
            self.signals.failed.emit("未获取到支付二维码")
            self.signals.finished.emit()
            return

        # 6. 发出信号让主线程显示二维码弹窗，然后结束当前线程
        self.signals.show_qr.emit(self.cookies, out_trade_no, self.course_id, qr_url)
        self.signals.progress.emit("等待扫码支付...")
        self.signals.finished.emit()
        # 支付成功后由主线程重新调用 _apply_credit


# ====== 账号条目 ======
class AccountItem:
    def __init__(self, username="", password=""):
        self.username = username
        self.password = password


# ====== 主窗口 ======
class FuzzyImportTool(QMainWindow):
    """主窗口"""

    def __init__(self):
        super().__init__()
        self._accounts = []
        self._current_category = None  # 当前选中的继续教育类型
        self._current_sub_category = None  # 当前选中的二级分类
        self._session_cookies = {}  # 登录后的 cookies
        self._ic_card = ""  # 登录后的 IC 卡号
        self._courses = []  # 当前课程列表
        self._category_sub_map = {
            "地方": ["临床、医技相关专项", "药学专项", "护理专项", "乡镇卫生院专项"],
            "省级": [
                "基础形态(1)", "基础机能(1)", "临床内科学(48)", "临床外科学(31)",
                "妇产科学(9)", "儿科学(8)", "眼、耳鼻喉学科(3)", "口腔医学学科(9)",
                "影像医学学科(15)", "急诊学(2)", "医学检验(19)", "公共卫生与预防医学(13)",
                "药学(14)", "护理学(94)", "医学教育与卫生管理学(10)", "康复医学(6)",
                "全科医学(4)", "中西医结合医学(12)", "中医学(66)", "民族医学(2)",
                "麻醉学(7)", "重症医学(5)", "皮肤病学与性病学(3)", "医院感染（管理）学(3)",
                "心理学(1)", "卫生法规与医学伦理学(4)",
            ],
        }
        self._sub_category_ids = {
            "临床、医技相关专项": "202610000035",
            "药学专项": "202610000036",
            "护理专项": "202610000034",
            "乡镇卫生院专项": "202610000037",
            # 省级（使用 P01-P26）
            "基础形态(1)": "P01", "基础机能(1)": "P02",
            "临床内科学(48)": "P03", "临床外科学(31)": "P04",
            "妇产科学(9)": "P05", "儿科学(8)": "P06",
            "眼、耳鼻喉学科(3)": "P07", "口腔医学学科(9)": "P08",
            "影像医学学科(15)": "P09", "急诊学(2)": "P10",
            "医学检验(19)": "P11", "公共卫生与预防医学(13)": "P12",
            "药学(14)": "P13", "护理学(94)": "P14",
            "医学教育与卫生管理学(10)": "P15", "康复医学(6)": "P16",
            "全科医学(4)": "P17", "中西医结合医学(12)": "P18",
            "中医学(66)": "P19", "民族医学(2)": "P20",
            "麻醉学(7)": "P21", "重症医学(5)": "P22",
            "皮肤病学与性病学(3)": "P23", "医院感染（管理）学(3)": "P24",
            "心理学(1)": "P25", "卫生法规与医学伦理学(4)": "P26",
        }
        self._select_all_state = False  # 全选状态
        self._clipboard_watcher = ClipboardWatcher(self._on_clipboard_changed)
        self._login_thread = None
        self._login_worker = None
        self._study_thread = None
        self._study_worker = None
        self._credit_thread = None
        self._credit_worker = None
        self._init_ui()
        self._setup_clipboard_monitor()

        # 首次运行检查超级鹰配置
        if SUPER_EAGLE_USER == "your_username":
            print("⚠️ 请先编辑 fuzzy_import_tool.py 中的超级鹰账号密码")

    def _init_ui(self):
        self.setWindowTitle("模糊导入工具 v1.0")
        self.setMinimumSize(980, 760)
        self.resize(980, 760)
        self.setStyleSheet("""
            QMainWindow { background-color: #f5f5f5; }
        """)

        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(10, 6, 10, 6)
        main_layout.setSpacing(4)

        # ====== 第一行：用户名 + 密码 + 操作按钮 ======
        top_group = QGroupBox("账号信息")
        top_group.setStyleSheet("""
            QGroupBox {
                font-weight: bold; font-size: 11px;
                border: 1px solid #d0d0d0; border-radius: 3px;
                margin-top: 4px; padding-top: 12px;
                background: white;
            }
            QGroupBox::title {
                subcontrol-origin: margin; left: 8px; padding: 0 3px;
            }
        """)
        top_layout = QHBoxLayout(top_group)
        top_layout.setSpacing(8)

        lbl_user = QLabel("用户名:")
        lbl_user.setMinimumWidth(55)
        self.txt_username = QLineEdit()
        self.txt_username.setPlaceholderText("输入或从剪贴板导入...")
        self.txt_username.setMinimumHeight(24)
        self.txt_username.setStyleSheet("""
            QLineEdit {
                border: 1px solid #c8c8c8; border-radius: 3px;
                padding: 2px 5px; font-size: 12px;
            }
            QLineEdit:focus { border-color: #4a90d9; }
        """)

        lbl_pwd = QLabel("密码:")
        lbl_pwd.setMinimumWidth(35)
        self.txt_password = QLineEdit()
        self.txt_password.setPlaceholderText("输入或从剪贴板导入...")
        self.txt_password.setMinimumHeight(24)
        self.txt_password.setStyleSheet(self.txt_username.styleSheet())
        self.txt_password.setEchoMode(QLineEdit.Normal)

        btn_import_style = """
            QPushButton {
                border: 1px solid #4a90d9; border-radius: 4px;
                background-color: #4a90d9; color: white;
                font-weight: bold; font-size: 12px; padding: 3px 12px;
            }
            QPushButton:hover { background-color: #357abd; }
            QPushButton:pressed { background-color: #2a6cb5; }
        """

        # 模糊导入
        self.btn_import = QPushButton("📋 模糊导入")
        self.btn_import.setMinimumHeight(24)
        self.btn_import.setStyleSheet(btn_import_style)
        self.btn_import.clicked.connect(self._fuzzy_import)

        # 登录
        self.btn_login = QPushButton("登录")
        self.btn_login.setMinimumHeight(24)
        self.btn_login.setStyleSheet("""
            QPushButton {
                border: 1px solid #52c41a; border-radius: 4px;
                background-color: #52c41a; color: white;
                font-weight: bold; font-size: 12px; padding: 3px 12px;
            }
            QPushButton:hover { background-color: #45a818; }
            QPushButton:pressed { background-color: #38900d; }
        """)
        self.btn_login.clicked.connect(self._login)

        # 刷新课程
        self.btn_refresh = QPushButton("刷新课程")
        self.btn_refresh.setMinimumHeight(24)
        self.btn_refresh.setStyleSheet("""
            QPushButton {
                border: 1px solid #1890ff; border-radius: 4px;
                background-color: #1890ff; color: white;
                font-weight: bold; font-size: 12px; padding: 3px 12px;
            }
            QPushButton:hover { background-color: #1479d3; }
            QPushButton:pressed { background-color: #1068b8; }
        """)
        self.btn_refresh.clicked.connect(self._refresh_courses)

        # 清空
        self.btn_clear = QPushButton("清空输入")
        self.btn_clear.setMinimumHeight(24)
        self.btn_clear.setStyleSheet("""
            QPushButton {
                border: 1px solid #bbb; border-radius: 4px;
                padding: 3px 12px; background: white; font-size: 12px;
            }
            QPushButton:hover { background: #f0f0f0; }
        """)
        self.btn_clear.clicked.connect(self._clear_inputs)

        top_layout.addWidget(lbl_user)
        top_layout.addWidget(self.txt_username, 2)
        top_layout.addWidget(lbl_pwd)
        top_layout.addWidget(self.txt_password, 2)
        top_layout.addWidget(self.btn_import)
        top_layout.addWidget(self.btn_login)
        top_layout.addWidget(self.btn_refresh)
        top_layout.addWidget(self.btn_clear)

        main_layout.addWidget(top_group)

        # ====== 继续教育类型选择 ======
        cat_group = QGroupBox("继续教育类型")
        cat_group.setStyleSheet("""
            QGroupBox {
                font-weight: bold; font-size: 11px;
                border: 1px solid #d0d0d0; border-radius: 3px;
                margin-top: 3px; padding-top: 11px;
                background: white;
            }
            QGroupBox::title {
                subcontrol-origin: margin; left: 8px; padding: 0 3px;
            }
        """)
        cat_layout = QHBoxLayout(cat_group)
        cat_layout.setSpacing(8)

        self.btn_local = QPushButton("地方继续教育")
        self.btn_local.setMinimumHeight(22)
        self.btn_local.setStyleSheet("""
            QPushButton {
                border: 2px solid #4a90d9; border-radius: 3px;
                background-color: #f0f5ff; color: #2b6cb0;
                font-weight: bold; font-size: 11px; padding: 1px 8px;
            }
            QPushButton:hover { background-color: #d6e4ff; border-color: #357abd; }
            QPushButton:pressed { background-color: #b3cfff; }
            QPushButton[selected="true"] {
                background-color: #4a90d9; color: white;
                border-color: #357abd;
            }
        """)
        self.btn_local.clicked.connect(lambda: self._select_category("地方"))

        self.btn_corps = QPushButton("兵团继续教育")
        self.btn_corps.setMinimumHeight(26)
        self.btn_corps.setStyleSheet("""
            QPushButton {
                border: 2px solid #4a90d9; border-radius: 4px;
                background-color: #f0f5ff; color: #2b6cb0;
                font-weight: bold; font-size: 11px; padding: 2px 10px;
            }
            QPushButton:hover { background-color: #d6e4ff; border-color: #357abd; }
            QPushButton:pressed { background-color: #b3cfff; }
            QPushButton[selected="true"] {
                background-color: #4a90d9; color: white;
                border-color: #357abd;
            }
        """)
        self.btn_corps.clicked.connect(lambda: self._select_category("兵团"))

        self.btn_province = QPushButton("省级继续教育")
        self.btn_province.setMinimumHeight(26)
        self.btn_province.setStyleSheet("""
            QPushButton {
                border: 2px solid #4a90d9; border-radius: 4px;
                background-color: #f0f5ff; color: #2b6cb0;
                font-weight: bold; font-size: 11px; padding: 2px 10px;
            }
            QPushButton:hover { background-color: #d6e4ff; border-color: #357abd; }
            QPushButton:pressed { background-color: #b3cfff; }
            QPushButton[selected="true"] {
                background-color: #4a90d9; color: white;
                border-color: #357abd;
            }
        """)
        self.btn_province.clicked.connect(lambda: self._select_category("省级"))

        cat_layout.addWidget(self.btn_local, 1)
        cat_layout.addWidget(self.btn_corps, 1)
        cat_layout.addWidget(self.btn_province, 1)
        main_layout.addWidget(cat_group)

        # ====== 二级分类（隐藏，选中主分类后显示） ======
        self.sub_group = QGroupBox("二级分类")
        self.sub_group.setStyleSheet("""
            QGroupBox {
                font-weight: bold; font-size: 11px;
                border: 1px solid #d0d0d0; border-radius: 3px;
                margin-top: 2px; padding-top: 10px;
                background: white;
            }
            QGroupBox::title {
                subcontrol-origin: margin; left: 8px; padding: 0 3px;
            }
        """)
        # 使用自定义 QWidget + FlowLayout
        self.sub_container = QWidget()
        self.sub_flow = FlowLayout(self.sub_container, margin=6, spacing=6)
        self.sub_group_layout = QVBoxLayout(self.sub_group)
        self.sub_group_layout.setContentsMargins(0, 0, 0, 0)
        self.sub_group_layout.addWidget(self.sub_container)

        self._sub_buttons = []

        # 默认隐藏二级分类
        self.sub_group.setVisible(False)
        main_layout.addWidget(self.sub_group)

        # 初始禁用分类按钮（需登录后才可操作）
        self.btn_local.setEnabled(False)
        self.btn_corps.setEnabled(False)
        self.btn_province.setEnabled(False)

        # ====== 课程列表 ======
        self.course_group = QGroupBox("课程列表")
        self.course_group.setStyleSheet("""
            QGroupBox {
                font-weight: bold; font-size: 11px;
                border: 1px solid #d0d0d0; border-radius: 3px;
                margin-top: 3px; padding-top: 11px;
                background: white;
            }
            QGroupBox::title {
                subcontrol-origin: margin; left: 8px; padding: 0 3px;
            }
        """)
        course_layout = QVBoxLayout(self.course_group)

        # 工具栏：全选 + 学习按钮
        tool_bar = QHBoxLayout()
        self.cb_select_all = QPushButton("☐ 全选")
        self.cb_select_all.setFixedHeight(28)
        self.cb_select_all.setStyleSheet("""
            QPushButton {
                border: 1px solid #bbb; border-radius: 3px;
                padding: 2px 10px; background: white; font-size: 12px;
            }
            QPushButton:hover { background: #eee; }
        """)
        self.cb_select_all.clicked.connect(self._toggle_select_all)
        tool_bar.addWidget(self.cb_select_all)

        self.lbl_selected = QLabel("已选 0 门")
        self.lbl_selected.setStyleSheet("font-size: 12px; color: #666; padding: 0 8px;")
        tool_bar.addWidget(self.lbl_selected)

        tool_bar.addStretch()

        self.btn_study = QPushButton("📖 学习选中课程")
        self.btn_study.setFixedHeight(28)
        self.btn_study.setEnabled(False)
        self.btn_study.setStyleSheet("""
            QPushButton {
                border: 1px solid #52c41a; border-radius: 3px;
                background-color: #52c41a; color: white;
                font-weight: bold; font-size: 12px; padding: 2px 14px;
            }
            QPushButton:hover { background-color: #45a818; }
            QPushButton:disabled { background-color: #ccc; border-color: #ccc; }
        """)
        self.btn_study.clicked.connect(self._study_selected)
        tool_bar.addWidget(self.btn_study)
        course_layout.addLayout(tool_bar)

        # 表格：第0列为复选框，第5列为操作按钮
        self.course_table = QTableWidget()
        self.course_table.setColumnCount(6)
        self.course_table.setHorizontalHeaderLabels(["选择", "课程名称", "学分", "状态", "课程ID", "操作"])
        self.course_table.horizontalHeader().setStretchLastSection(False)
        for col in range(6):
            self.course_table.horizontalHeader().setSectionResizeMode(col, QHeaderView.Fixed)
        self.course_table.setColumnWidth(0, 40)    # 选择
        self.course_table.setColumnWidth(1, 300)   # 课程名称
        self.course_table.setColumnWidth(2, 85)    # 学分
        self.course_table.setColumnWidth(3, 110)   # 状态
        self.course_table.setColumnWidth(4, 95)    # 课程ID
        self.course_table.setColumnWidth(5, 100)   # 操作
        self.course_table.verticalHeader().setDefaultSectionSize(28)
        self.course_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.course_table.setAlternatingRowColors(True)
        self.course_table.setStyleSheet("""
            QTableWidget {
                border: 1px solid #d0d0d0; border-radius: 4px;
                font-size: 12px; gridline-color: #e8e8e8;
                background-color: white;
            }
            QTableWidget::item { padding: 4px 6px; }
            QHeaderView::section {
                background-color: #f0f5ff; color: #2b6cb0;
                font-weight: bold; padding: 4px 6px;
                border: none; border-bottom: 2px solid #4a90d9;
            }
        """)
        self.course_table.verticalHeader().setVisible(False)
        self.course_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.course_table.cellClicked.connect(self._on_course_cell_clicked)
        course_layout.addWidget(self.course_table)

        # 默认隐藏
        self.course_group.setVisible(False)
        main_layout.addWidget(self.course_group)

        # 状态栏
        self.statusBar().showMessage("就绪 — 按「模糊导入」从剪贴板提取账号密码")

    # ---- 日志辅助（已隐藏） ----
    def _log(self, msg):
        pass

    # ---- 剪贴板监控 ----
    def _setup_clipboard_monitor(self):
        self._clip_timer = QTimer()
        self._clip_timer.timeout.connect(self._clipboard_watcher.check)
        self._clip_timer.start(800)

    def _on_clipboard_changed(self, text):
        self._log(f"[剪贴板] 检测到新内容 ({len(text)}字符)")

    # ---- 模糊导入 ----
    def _fuzzy_import(self):
        text = QApplication.clipboard().text().strip()
        if not text:
            QMessageBox.information(self, "提示", "剪贴板为空，请先复制内容")
            return

        parts = text.split(None, 1)
        if len(parts) == 2:
            self.txt_username.setText(parts[0])
            self.txt_password.setText(parts[1])
            self.statusBar().showMessage(f"✅ 已导入: 用户名={parts[0]}")
            self._log(f"[导入] 用户名={parts[0]}, 密码={'*'*len(parts[1])}")
            return

        if '\t' in text:
            parts = text.split('\t', 1)
            if len(parts) == 2 and parts[0] and parts[1]:
                self.txt_username.setText(parts[0])
                self.txt_password.setText(parts[1])
                self.statusBar().showMessage(f"✅ 已导入(Tab分隔): {parts[0]}")
                self._log(f"[导入Tab] 用户名={parts[0]}")
                return

        for sep in [':', '：', ',', '，', '|']:
            if sep in text:
                parts = text.split(sep, 1)
                if len(parts) == 2 and parts[0] and parts[1]:
                    self.txt_username.setText(parts[0].strip())
                    self.txt_password.setText(parts[1].strip())
                    self.statusBar().showMessage(f"✅ 已导入({sep}分隔): {parts[0].strip()}")
                    self._log(f"[导入{sep}] 用户名={parts[0].strip()}")
                    return

        self.txt_username.setText(text)
        self.txt_password.setText("")
        self.statusBar().showMessage("⚠️ 未识别到分隔符，已填入用户名（密码为空）")
        self._log(f"[导入] 未识别分隔符，全部当作用户名: {text}")

    # ---- 清空 ----
    def _clear_inputs(self):
        self.txt_username.clear()
        self.txt_password.clear()
        self.statusBar().showMessage("已清空")
        self._log("[清空] 已清空输入")

    # ---- 登录 ---- # noqa: C901
    def _login(self):
        username = self.txt_username.text().strip()
        password = self.txt_password.text().strip()
        if not username or not password:
            self.statusBar().showMessage("⚠️ 用户名和密码不能为空")
            return

        # 禁用按钮，避免重复点击
        self.btn_login.setEnabled(False)
        self.btn_login.setText("登录中...")
        self.btn_import.setEnabled(False)
        self._log(f"[登录] 开始登录 {username} ...")

        # 创建工作线程
        self._login_worker = LoginWorker(username, password)
        self._login_thread = QThread()
        self._login_worker.moveToThread(self._login_thread)

        # 连接信号
        self._login_worker.signals.started.connect(lambda: self._log("[登录] 线程启动..."))
        self._login_worker.signals.progress.connect(self._log)
        self._login_worker.signals.finished.connect(self._on_login_finished)
        self._login_thread.started.connect(self._login_worker.run)
        self._login_thread.finished.connect(self._login_thread.deleteLater)

        self._login_thread.start()

    def _on_login_finished(self, status, detail, elapsed, cookies, ic_card):
        """登录完成回调（主线程）"""
        if self._login_thread:
            self._login_thread.quit()
            self._login_thread.wait()
            self._login_thread = None
        self._login_worker = None

        self.btn_login.setEnabled(True)
        self.btn_login.setText("登录")
        self.btn_import.setEnabled(True)

        if status == "成功":
            self._session_cookies = cookies
            self._ic_card = ic_card
            # 启用分类按钮
            for btn in [self.btn_local, self.btn_corps, self.btn_province]:
                btn.setEnabled(True)
            self.statusBar().showMessage(f"✅ {detail} (耗时{elapsed})")
            self._log(f"[登录] ✅ 成功! {detail} (耗时{elapsed})")
        elif status == "已取消":
            self.statusBar().showMessage("已取消登录")
            self._log("[登录] 已取消")
        else:
            self.statusBar().showMessage(f"❌ {status}: {detail}")
            self._log(f"[登录] ❌ {status}: {detail} (耗时{elapsed})")

    # ---- 刷新课程 ----
    def _refresh_courses(self):
        """根据当前一二级分类重新获取课程列表"""
        if not self._current_category:
            self._log("[刷新] ⚠️ 请先选择继续教育类型")
            self.statusBar().showMessage("⚠️ 请先选择继续教育类型")
            return
        if not self._current_sub_category:
            self._log("[刷新] ⚠️ 请先选择二级分类")
            self.statusBar().showMessage("⚠️ 请先选择二级分类")
            return
        self._log(f"[刷新] 重新获取: {self._current_category} > {self._current_sub_category}")
        self._fetch_courses(self._current_sub_category)

    # ---- 继续教育类型选择 ----
    def _select_category(self, cat):
        """选择继续教育类型"""
        self._current_category = cat

        # 重置所有按钮样式
        for btn in [self.btn_local, self.btn_corps, self.btn_province]:
            btn.setProperty("selected", False)
            btn.style().unpolish(btn)
            btn.style().polish(btn)

        # 高亮选中按钮
        selected = {"地方": self.btn_local, "兵团": self.btn_corps, "省级": self.btn_province}[cat]
        selected.setProperty("selected", True)
        selected.style().unpolish(selected)
        selected.style().polish(selected)

        msg = f"已选择: {cat}继续教育"
        self.statusBar().showMessage(msg)
        self._log(f"[类型] {msg}")

        # 清空课程列表
        self.course_table.setRowCount(0)
        self.course_group.setVisible(False)
        self._courses = []

        # 显示/隐藏二级分类
        sub_list = self._category_sub_map.get(cat, [])
        if sub_list:
            # 清空旧按钮，动态创建新按钮
            self._rebuild_sub_buttons(sub_list)
            self.sub_group.setVisible(True)
            self._current_sub_category = None
        else:
            self.sub_group.setVisible(False)
            self._current_sub_category = None

    def _rebuild_sub_buttons(self, names):
        """根据分类名称列表重建二级分类按钮"""
        # 从 FlowLayout 中移除旧按钮
        for btn in self._sub_buttons:
            self.sub_flow.removeWidget(btn)
            btn.deleteLater()
        self._sub_buttons = []

        for name in names:
            btn = QPushButton(name)
            btn.setMinimumHeight(26)
            btn.setStyleSheet("""
                QPushButton {
                    border: 1.5px solid #7eb8ea; border-radius: 3px;
                    background-color: #f5f9ff; color: #2b6cb0;
                    font-size: 11px; padding: 3px 10px;
                }
                QPushButton:hover { background-color: #dce8f7; border-color: #4a90d9; }
                QPushButton:pressed { background-color: #c0d6f0; }
                QPushButton[selected="true"] {
                    background-color: #4a90d9; color: white;
                    border-color: #357abd;
                }
            """)
            btn.clicked.connect(lambda checked, n=name: self._select_sub_category(n))
            self.sub_flow.addWidget(btn)
            self._sub_buttons.append(btn)

    def _select_sub_category(self, name):
        """选择二级分类 → 获取课程列表"""
        self._current_sub_category = name
        # 高亮选中的子按钮
        for btn in self._sub_buttons:
            btn.setProperty("selected", btn.text() == name)
            btn.style().unpolish(btn)
            btn.style().polish(btn)
        msg = f"{self._current_category}继续教育 → {name}"
        self.statusBar().showMessage(msg)
        self._log(f"[二级分类] {msg}")

        # 获取课程
        self._fetch_courses(name)

    def _fetch_courses(self, sub_category):
        """使用已登录的 session 获取课程页面"""
        if not self._session_cookies:
            self._log("[课程] ⚠️ 请先登录")
            self.statusBar().showMessage("⚠️ 请先登录后再获取课程")
            return

        # 拼接 URL（根据子分类ID和主分类）
        cat_id = self._sub_category_ids.get(sub_category, "202610000035")
        if self._current_category == "省级":
            url = f"https://www.xjyxjyw.com/member/course_xj1list.do?courseCredit.subject={cat_id}"
        else:
            url = f"https://www.xjyxjyw.com/member/cw_info.do?id={cat_id}&card={self._ic_card}"
        self._log(f"[课程] 正在获取: {url}")
        self.statusBar().showMessage("正在获取课程列表...")

        try:
            sess = requests.Session()
            sess.headers.update({
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                              "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36"
            })
            # 设置 cookies
            for k, v in self._session_cookies.items():
                sess.cookies.set(k, v)

            r = sess.get(url, timeout=15)
            self._log(f"[课程] 页面状态码: {r.status_code}")
            self._log(f"[课程] 页面大小: {len(r.text)} 字符")

            # 解析课程列表
            if self._current_category == "省级":
                courses = self._fetch_all_province_pages(sess, url, r.text)
            else:
                courses = self._parse_course_list(r.text)
            self._courses = courses
            self._log(f"[课程] 共找到 {len(courses)} 门课程")

            # 填入表格
            self.course_table.setRowCount(len(courses))
            # 重置表格前清除所有 cell widget，防止旧按钮残留
            for row in range(self.course_table.rowCount()):
                for col in range(self.course_table.columnCount()):
                    self.course_table.removeCellWidget(row, col)
            self._select_all_state = False
            self.cb_select_all.setText("☐ 全选")
            for i, c in enumerate(courses):
                # 第0列：复选框
                check_item = QTableWidgetItem()
                check_item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                check_item.setCheckState(Qt.Unchecked)
                self.course_table.setItem(i, 0, check_item)

                name_item = QTableWidgetItem(c["name"])
                credit_item = QTableWidgetItem(c["credit"])
                status_text = f"{c['status']}"
                status_item = QTableWidgetItem(status_text)
                id_item = QTableWidgetItem(c["id"])

                name_item.setToolTip(c["name"])
                status_item.setToolTip(c["status"])

                self.course_table.setItem(i, 1, name_item)
                self.course_table.setItem(i, 2, credit_item)
                self.course_table.setItem(i, 3, status_item)
                self.course_table.setItem(i, 4, id_item)

                # 第5列：申请学分按钮
                if c.get("has_credit_link"):
                    btn_credit = QPushButton("申请学分")
                    btn_credit.setFixedHeight(24)
                    btn_credit.setStyleSheet("""
                        QPushButton {
                            border: 1px solid #fa8c16; border-radius: 3px;
                            background-color: #fff7e6; color: #d46b08;
                            font-size: 11px; padding: 2px 8px;
                        }
                        QPushButton:hover { background-color: #ffe7ba; }
                    """)
                    btn_credit.clicked.connect(lambda checked, cid=c["id"]: self._apply_credit(cid))
                    self.course_table.setCellWidget(i, 5, btn_credit)
                else:
                    empty_item = QTableWidgetItem("")
                    empty_item.setFlags(Qt.NoItemFlags)
                    self.course_table.setItem(i, 5, empty_item)

            self._update_selected_count()
            self.course_group.setVisible(True)
            self.statusBar().showMessage(f"共 {len(courses)} 门课程")
        except Exception as e:
            self._log(f"[课程] ❌ 请求失败: {e}")
            self.statusBar().showMessage(f"❌ 课程获取失败: {e}")

    def _parse_course_list(self, html):
        """解析课程列表 HTML → [{name, credit, status, id}, ...]"""
        courses = []
        # 按 <tr> 分割
        tr_pattern = re.compile(r'<tr>(.*?)</tr>', re.DOTALL)
        # 提取每个 tr 中的 3 个 td
        td_pattern = re.compile(r'<td[^>]*>(.*?)</td>', re.DOTALL)
        # 提取课程 ID
        id_pattern = re.compile(r'cw_info\.do\?id=(\d+)')

        for tr in tr_pattern.findall(html):
            tds = td_pattern.findall(tr)
            if len(tds) < 3:
                continue

            name = re.sub(r'<[^>]+>', '', tds[0]).strip()
            credit = re.sub(r'<[^>]+>', '', tds[1]).strip()
            status_td = tds[2]

            # 提取状态文字（去除HTML标签后取纯文本，排除操作按钮文字）
            status_text = re.sub(r'<[^>]+>', '', status_td).strip()
            # 去掉多余的空白
            status_text = re.sub(r'\s+', '', status_text)
            # 过滤掉操作类文字
            for skip in ["开始学习", "继续学习", "点击学习", "申请学分"]:
                status_text = status_text.replace(skip, "")
            status = status_text.strip() if status_text.strip() else "未知"

            # 检查是否有"申请学分"链接
            has_credit_link = "申请学分" in status_td and ("考试通过" in status_td or "通过考试" in status_td)

            # 提取课程 ID
            id_match = id_pattern.search(status_td)
            course_id = id_match.group(1) if id_match else ""

            if name and credit:
                courses.append({
                    "name": name,
                    "credit": credit,
                    "status": status,
                    "id": course_id,
                    "has_credit_link": has_credit_link,
                })

        return courses

    def _fetch_all_province_pages(self, sess, base_url, first_page_html):
        """省级分类：获取所有分页的课程并合并"""
        courses = self._parse_province_course_list(first_page_html)

        # 解析分页信息
        soup = BeautifulSoup(first_page_html, "html.parser")
        pagination = soup.find("ul", class_="pagination")
        total_pages = 1
        if pagination:
            text = pagination.get_text()
            m = re.search(r'共\s*(\d+)\s*页', text)
            if m:
                total_pages = int(m.group(1))

        if total_pages <= 1:
            return courses

        self._log(f"[课程] 共 {total_pages} 页，正在获取剩余页面...")
        for page in range(2, total_pages + 1):
            page_url = f"{base_url}&currPage={page}"
            try:
                r = sess.get(page_url, timeout=15)
                page_courses = self._parse_province_course_list(r.text)
                courses.extend(page_courses)
                self._log(f"[课程] 第 {page} 页: {len(page_courses)} 门")
            except Exception as e:
                self._log(f"[课程] 第 {page} 页获取失败: {e}")

        return courses

    def _parse_province_course_list(self, html):
        """解析省级课程列表（div.blog-posts > div.row 结构）"""
        courses = []
        soup = BeautifulSoup(html, "html.parser")
        course_id_pattern = re.compile(r'courseWare\.courseId=(\d+)')

        # 只查找 blog-posts 内的 div.row（排除页面布局的 row）
        blog_posts = soup.find("div", class_="blog-posts")
        if not blog_posts:
            return courses

        for row_div in blog_posts.find_all("div", class_="row"):
            h2 = row_div.find("h2")
            if not h2:
                continue

            name = h2.get_text(strip=True)
            if not name:
                continue

            # 学分（ul.blog-info 的第2个 li）
            credit = ""
            blog_info = row_div.find("ul", class_="blog-info")
            if blog_info:
                lis = blog_info.find_all("li")
                if len(lis) >= 2:
                    credit = lis[1].get_text(strip=True)

            # 状态：取最后一个非空且非级别/学分/编号/人名的li
            status = "未知"
            if blog_info:
                status_li = blog_info.find_all("li")
                for li in reversed(status_li):
                    # 用正则提取纯文本（比 get_text 更可靠）
                    text = re.sub(r'<[^>]+>', '', str(li)).strip()
                    text = re.sub(r'\s+', '', text)
                    if not text:
                        continue
                    # 跳过学分字段（如 "3.0分"、"自治区级12" 等），但不跳过包含"分"的状态
                    if re.search(r'[\d.]+\s*分', text) or text in ("自治区级", "兵团级", "国家级"):
                        continue
                    if "省)" in text or "兵团)" in text:
                        continue
                    # 跳过纯数字（编号）
                    if re.match(r'^[\d\-]+$', text):
                        continue
                    status = text
                    break

            # 课程ID（a[href*=courseWare.courseId]）
            link = row_div.find("a", href=course_id_pattern)
            course_id = ""
            if link and "href" in link.attrs:
                m = course_id_pattern.search(link["href"])
                if m:
                    course_id = m.group(1)

            # 判断是否有申请学分链接
            has_credit_link = "通过考试" in status or "考试通过" in status

            courses.append({
                "name": name,
                "credit": credit,
                "status": status,
                "id": course_id,
                "has_credit_link": has_credit_link,
            })

        return courses

    # ---- 课程选择与学习 ----
    def _toggle_select_all(self):
        """全选/取消全选"""
        self._select_all_state = not self._select_all_state
        state = Qt.Checked if self._select_all_state else Qt.Unchecked
        self.cb_select_all.setText("☑ 全选" if self._select_all_state else "☐ 全选")
        for row in range(self.course_table.rowCount()):
            item = self.course_table.item(row, 0)
            if item:
                item.setCheckState(state)
        self._update_selected_count()

    def _on_course_cell_clicked(self, row, col):
        """点击单元格时更新选中计数"""
        if col == 0:
            self._update_selected_count()

    def _update_selected_count(self):
        """统计选中的课程数，更新标签和学习按钮状态"""
        count = 0
        for row in range(self.course_table.rowCount()):
            item = self.course_table.item(row, 0)
            if item and item.checkState() == Qt.Checked:
                count += 1
        self.lbl_selected.setText(f"已选 {count} 门")
        self.btn_study.setEnabled(count > 0)

    def _study_selected(self):
        """学习选中的课程"""
        selected = []
        for row in range(self.course_table.rowCount()):
            check_item = self.course_table.item(row, 0)
            if check_item and check_item.checkState() == Qt.Checked:
                name_item = self.course_table.item(row, 1)
                id_item = self.course_table.item(row, 4)
                selected.append({
                    "name": name_item.text() if name_item else "",
                    "id": id_item.text() if id_item else "",
                })

        if not selected:
            return

        self._log(f"[学习] 开始学习 {len(selected)} 门课程...")
        self.btn_study.setEnabled(False)
        self.btn_study.setText("学习中...")

        # 创建工作线程
        self._study_worker = StudyWorker(self._session_cookies, selected)
        self._study_thread = QThread()
        self._study_worker.moveToThread(self._study_thread)

        self._study_worker.signals.started.connect(lambda: self._log("[学习] 线程启动"))
        self._study_worker.signals.progress.connect(self._log)
        self._study_worker.signals.course_start.connect(self._on_course_start)
        self._study_worker.signals.video_done.connect(self._on_video_done)
        self._study_worker.signals.finished.connect(self._on_study_finished)
        self._study_thread.started.connect(self._study_worker.run)
        self._study_thread.finished.connect(self._study_thread.deleteLater)

        self._study_thread.start()

    def _on_course_start(self, course_name, total_videos):
        self._log(f"[学习] 📚 {course_name}: 共 {total_videos} 个视频")
        self.statusBar().showMessage(f"学习中: {course_name}")

    def _on_video_done(self, video_title, status, detail):
        icons = {"已学习": "✅", "通过考试": "🎉", "失败": "❌", "考试失败": "❌"}
        icon = icons.get(status, "➡")
        self._log(f"  {icon} {video_title} → {status}")

    def _on_study_finished(self, success, summary):
        if self._study_thread:
            self._study_thread.quit()
            self._study_thread.wait()
            self._study_thread = None
        self._study_worker = None

        self.btn_study.setEnabled(True)
        self.btn_study.setText("📖 学习选中课程")

        if success:
            self._log(f"[学习] ✅ {summary}")
        else:
            self._log(f"[学习] ⚠️ {summary}")
        self.statusBar().showMessage(summary)

        # 学习完后自动刷新课程列表
        QTimer.singleShot(1000, self._refresh_courses)

    def _apply_credit(self, course_id):
        """为指定课程申请学分"""
        # 找到课程名称
        course_name = course_id
        for c in self._courses:
            if c["id"] == course_id:
                course_name = c["name"]
                break

        self._log(f"[申请学分] {course_name} ({course_id})")
        self.statusBar().showMessage(f"申请学分中: {course_name}")
        self.btn_study.setEnabled(False)

        # 创建工作线程
        self._credit_worker = CreditWorker(self._session_cookies, course_id, course_name)
        self._credit_thread = QThread()
        self._credit_worker.moveToThread(self._credit_thread)

        self._credit_worker.signals.started.connect(lambda: self._log("[申请学分] 线程启动"))
        self._credit_worker.signals.progress.connect(self._log)
        self._credit_worker.signals.success.connect(self._on_credit_success)
        self._credit_worker.signals.failed.connect(self._on_credit_failed)
        self._credit_worker.signals.show_qr.connect(self._show_qr_dialog)
        self._credit_worker.signals.finished.connect(self._on_credit_finished)
        self._credit_thread.started.connect(self._credit_worker.run)
        self._credit_thread.finished.connect(self._credit_thread.deleteLater)

        self._credit_thread.start()

    def _on_credit_success(self, detail):
        self._log(f"[申请学分] ✅ {detail}")
        self.statusBar().showMessage(f"✅ {detail}")
        QTimer.singleShot(500, self._refresh_courses)

    def _on_credit_failed(self, reason):
        self._log(f"[申请学分] ❌ {reason}")
        self.statusBar().showMessage(f"❌ {reason}")

    def _on_credit_finished(self):
        if self._credit_thread:
            self._credit_thread.quit()
            self._credit_thread.wait()
            self._credit_thread = None
        self._credit_worker = None
        self.btn_study.setEnabled(True)

    def _apply_after_pay(self, cookies, course_id):
        """支付成功后，直接检查卡余额并申请学分（不走购卡流程）"""
        self._log("[申请学分] 支付完成，检查卡余额...")
        import threading
        def do_apply():
            sess = requests.Session()
            sess.headers.update({
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                              "AppleWebKit/537.36"
            })
            if cookies:
                for k, v in cookies.items():
                    sess.cookies.set(k, v)
            try:
                r = sess.get(f"https://www.xjyxjyw.com/member/apply_apply.do?course_id={course_id}", timeout=15)
                # 找可用卡并申请
                import re
                for tr in re.findall(r'<tr[^>]*>(.*?)</tr>', r.text, re.DOTALL):
                    if "使用此卡申请" not in tr:
                        continue
                    tds = re.findall(r'<td[^>]*>(.*?)</td>', tr, re.DOTALL)
                    if len(tds) < 5:
                        continue
                    nums = re.findall(r'\d+', tr)
                    cn, cp = "", ""
                    for n in nums:
                        if len(n) >= 10 and not cn:
                            cn = n
                        elif len(n) >= 4 and cn and not cp:
                            cp = n
                    if not cn or not cp:
                        continue
                    try:
                        s = float(re.sub(r'[^\d.]', '', re.sub(r'<[^>]+>', '', tds[4])))
                    except ValueError:
                        s = 0
                    if s <= 0:
                        continue
                    # 有可用卡 → 申请
                    apply_url = (f"https://www.xjyxjyw.com/member/apply_applyCard.do"
                                 f"?courseLog.cid={course_id}&cardNo={cn}&cardPasswd={cp}")
                    resp = sess.get(apply_url, timeout=15)
                    if "申请成功" in resp.text:
                        self._log(f"[申请学分] ✅ 申请成功")
                        self.statusBar().showMessage("✅ 申请成功")
                        # 刷新课程列表
                        QTimer.singleShot(500, self._refresh_courses)
                    else:
                        self._log(f"[申请学分] ❌ 申请失败")
                    return
                self._log("[申请学分] ⚠️ 卡余额仍未更新，请稍后刷新重试")
                self.statusBar().showMessage("⚠️ 请刷新后重试")
            except Exception as e:
                self._log(f"[申请学分] ❌ 请求异常: {e}")

        threading.Thread(target=do_apply, daemon=True).start()

    def _show_qr_dialog(self, cookies, out_trade_no, course_id, qr_url):
        """显示微信支付二维码弹窗 + 轮询支付状态"""
        from PyQt5.QtWidgets import QDialog, QVBoxLayout, QLabel
        dialog = QDialog(self)
        dialog.setWindowTitle("微信扫码支付")
        dialog.setFixedSize(340, 420)
        layout = QVBoxLayout(dialog)

        # 二维码区域：尝试显示二维码图片，失败则显示链接和"在浏览器打开"按钮
        qr_label = QLabel()
        qr_label.setAlignment(Qt.AlignCenter)
        qr_label.setMinimumSize(280, 280)
        qr_ok = False
        try:
            import qrcode
            from io import BytesIO
            from PyQt5.QtGui import QPixmap
            qr_img = qrcode.make(qr_url)
            buf = BytesIO()
            qr_img.save(buf, format="PNG")
            pixmap = QPixmap()
            if pixmap.loadFromData(buf.getvalue()):
                qr_label.setPixmap(pixmap.scaled(280, 280, Qt.KeepAspectRatio, Qt.SmoothTransformation))
                qr_ok = True
        except Exception:
            pass

        if not qr_ok:
            qr_label.setText("请点击下方按钮在浏览器中打开支付页面")
            qr_label.setStyleSheet("font-size: 12px; color: #666;")
        layout.addWidget(qr_label)

        # 浏览器打开按钮
        btn_open = QPushButton("🌐 在浏览器中打开支付")
        btn_open.setStyleSheet("""
            QPushButton {
                border: 1px solid #4a90d9; border-radius: 4px;
                background-color: #4a90d9; color: white;
                font-weight: bold; font-size: 12px; padding: 6px;
            }
            QPushButton:hover { background-color: #357abd; }
        """)
        btn_open.clicked.connect(lambda: __import__("webbrowser").open(qr_url))
        layout.addWidget(btn_open)

        info = QLabel(f"订单号: {out_trade_no[-8:]}\n微信扫码支付，支付后自动申请学分")
        info.setAlignment(Qt.AlignCenter)
        info.setStyleSheet("font-size: 12px; padding: 4px;")
        layout.addWidget(info)

        btn_close = QPushButton("关闭")
        btn_close.clicked.connect(dialog.reject)
        layout.addWidget(btn_close)

        # 轮询支付状态
        self._poll_count_qr = 0
        poll_timer = QTimer()

        def poll_state():
            self._poll_count_qr += 1
            try:
                sess = requests.Session()
                sess.headers.update({"User-Agent": "Mozilla/5.0"})
                if cookies:
                    for k, v in cookies.items():
                        sess.cookies.set(k, v)
                ts = int(time.time() * 1000)
                resp = sess.get(
                    f"https://www.xjyxjyw.com/member/myCard_state.do?out_trade_no={out_trade_no}&t={ts}",
                    timeout=10)
                text = resp.text.strip()
                self._log(f"[支付] 第{self._poll_count_qr}次轮询: {text[:80]}")
                if '":1"' in text or "':1'" in text or 'Satues:1' in text:
                    poll_timer.stop()
                    dialog.accept()
                    self._log("[支付] ✅ 支付成功，正在申请学分...")
                    self.statusBar().showMessage("支付成功，正在申请学分...")
                    # 支付成功后等待3秒让系统更新，然后直接申请（不走购卡流程）
                    QTimer.singleShot(3000, lambda: self._apply_after_pay(cookies, course_id))
            except Exception:
                pass
            if self._poll_count_qr > 120:
                poll_timer.stop()
                dialog.reject()

        poll_timer.timeout.connect(poll_state)
        poll_timer.start(3000)

        dialog.exec_()
        if poll_timer.isActive():
            poll_timer.stop()

    def _get_status_icon(self, status_text):
        """根据状态文字返回对应图标（模糊匹配）"""
        # 按优先级从高到低匹配
        pairs = [
            ("已申请学分", "📜"),
            ("考试通过", "🎉"),
            ("通过考试", "🎉"),
            ("已完成", "✅"),
            ("已学完", "✅"),
            ("未学习", "⬜"),
            ("学习中", "🔄"),
            ("看完课件", "📖"),
        ]
        for keyword, icon in pairs:
            if keyword in status_text:
                return icon
        return "❓"

    # ---- 复制 ----
    def _copy_username(self):
        text = self.txt_username.text()
        if text:
            QApplication.clipboard().setText(text)
            self.statusBar().showMessage(f"✅ 用户名已复制: {text}")
        else:
            self.statusBar().showMessage("⚠️ 用户名为空")

    def _copy_password(self):
        text = self.txt_password.text()
        if text:
            QApplication.clipboard().setText(text)
            self.statusBar().showMessage("✅ 密码已复制到剪贴板")
        else:
            self.statusBar().showMessage("⚠️ 密码为空")

    # ---- 窗口关闭时清理线程 ----
    def closeEvent(self, event):
        if self._login_worker:
            self._login_worker.cancel = True
        if self._login_thread and self._login_thread.isRunning():
            self._login_thread.quit()
            self._login_thread.wait()
        if self._study_worker:
            self._study_worker.cancel = True
        if self._study_thread and self._study_thread.isRunning():
            self._study_thread.quit()
            self._study_thread.wait()
        if self._credit_worker:
            self._credit_worker.cancel = True
        if self._credit_thread and self._credit_thread.isRunning():
            self._credit_thread.quit()
            self._credit_thread.wait()
        event.accept()


# ====== 入口 ======
def main():
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    from PyQt5.QtGui import QPalette, QColor
    palette = QPalette()
    palette.setColor(QPalette.Window, QColor(245, 245, 245))
    palette.setColor(QPalette.WindowText, QColor(50, 50, 50))
    palette.setColor(QPalette.Base, QColor(255, 255, 255))
    palette.setColor(QPalette.AlternateBase, QColor(240, 240, 240))
    palette.setColor(QPalette.Button, QColor(255, 255, 255))
    palette.setColor(QPalette.ButtonText, QColor(50, 50, 50))
    palette.setColor(QPalette.Text, QColor(50, 50, 50))
    palette.setColor(QPalette.Highlight, QColor(74, 144, 217))
    palette.setColor(QPalette.HighlightedText, QColor(255, 255, 255))
    app.setPalette(palette)

    window = FuzzyImportTool()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
