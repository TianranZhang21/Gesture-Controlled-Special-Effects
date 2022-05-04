
#!/usr/bin/env python
# -*- coding: utf-8 -*-
import csv
import copy
import argparse
from collections import Counter
from collections import deque

import pyautogui

import cv2 as cv
import numpy as np
import mediapipe as mp

from KazuhitoTakahashiUtils import CvFpsCalc
from model import KeyPointClassifier
from model import PointHistoryClassifier

from KazuhitoTakahashiUtils.helpers import *

def cartoon_effect(frame): 
    # prepare color
    img_color = cv.pyrDown(cv.pyrDown(frame))
    for _ in range(3):
        img_color = cv.bilateralFilter(img_color, 9, 9, 7)
    img_color = cv.pyrUp(cv.pyrUp(img_color))

    # prepare edges
    img_edges = cv.cvtColor(frame, cv.COLOR_RGB2GRAY)
    img_edges = cv.adaptiveThreshold(
        cv.medianBlur(img_edges, 7), 255,
        cv.ADAPTIVE_THRESH_MEAN_C, cv.THRESH_BINARY,
        9, 2,)
    img_edges = cv.cvtColor(img_edges, cv.COLOR_GRAY2RGB)

    # combine color and edges
    frame = cv.bitwise_and(img_color, img_edges)
    return frame


def draw_point_history(image, point_history):
    pre = None
    for index, point in enumerate(point_history):
        if point[0] != 0 and point[1] != 0:
            if pre == None:
                pre = point
            else: 
                cv.line(image, pre, point, (200, 140, 30), 2)
                pre = point
    return image

def main():

    panorama_mode = False
    cartoon_mode = False
    drawing_mode = True

    use_brect = True

    # カメラ準備 ###############################################################
    cap = cv.VideoCapture(0)

    mp_hands = mp.solutions.hands
    hands = mp_hands.Hands(
        static_image_mode=True,
        max_num_hands=1,
        min_detection_confidence=0.7,
        min_tracking_confidence=0.5,
    )

    if (panorama_mode): 
        panorama = cv.imread('panorama.png')
        view_start = 0
        view_shift_speed = 1000
        #  view_shift_speed = 400

    keypoint_classifier = KeyPointClassifier()
    point_history_classifier = PointHistoryClassifier()
    canvas = np.zeros((1, 1, 3))

    # ラベル読み込み ###########################################################
    with open('model/keypoint_classifier/keypoint_classifier_label.csv',
              encoding='utf-8-sig') as f:
        keypoint_classifier_labels = csv.reader(f)
        keypoint_classifier_labels = [
            row[0] for row in keypoint_classifier_labels
        ]
    with open(
            'model/point_history_classifier/point_history_classifier_label.csv',
            encoding='utf-8-sig') as f:
        point_history_classifier_labels = csv.reader(f)
        point_history_classifier_labels = [
            row[0] for row in point_history_classifier_labels
        ]

    # FPS計測モジュール ########################################################
    cvFpsCalc = CvFpsCalc(buffer_len=10)

    # 座標履歴 #################################################################
    history_length = 16
    point_history = deque(maxlen=history_length)

    # フィンガージェスチャー履歴 ################################################
    finger_gesture_history = deque(maxlen=history_length)

    #  ########################################################################
    mode = 0

    while True:
        fps = cvFpsCalc.get()

        # キー処理(ESC：終了) #################################################
        key = cv.waitKey(10)
        if key == 27:  # ESC
            break
        number, mode = select_mode(key, mode)

        # カメラキャプチャ #####################################################
        ret, image = cap.read()
        if not ret:
            break
        image = cv.flip(image, 1)  # ミラー表示
        debug_image = copy.deepcopy(image)

        if (cartoon_mode): 
            debug_image = cartoon_effect(debug_image)

        # 検出実施 #############################################################
        image = cv.cvtColor(image, cv.COLOR_BGR2RGB)

        image.flags.writeable = False
        results = hands.process(image)
        image.flags.writeable = True

        #  ####################################################################
        if results.multi_hand_landmarks is not None:
            for hand_landmarks, handedness in zip(results.multi_hand_landmarks,
                                                  results.multi_handedness):
                # 外接矩形の計算
                brect = calc_bounding_rect(debug_image, hand_landmarks)
                # ランドマークの計算
                landmark_list = calc_landmark_list(debug_image, hand_landmarks)

                # 相対座標・正規化座標への変換
                pre_processed_landmark_list = pre_process_landmark(
                    landmark_list)
                pre_processed_point_history_list = pre_process_point_history(
                    debug_image, point_history)
                # 学習データ保存
                logging_csv(number, mode, pre_processed_landmark_list,
                            pre_processed_point_history_list)

                # ハンドサイン分類
                hand_sign_id = keypoint_classifier(pre_processed_landmark_list)
                #  print("hand_sign_id: ", hand_sign_id)

                #  if (hand_sign_id == 0): 
                #      view_start += view_shift_speed
                #      pyautogui.scroll(-5)
                #  elif (hand_sign_id == 1): 
                #      view_start -= view_shift_speed
                #      pyautogui.scroll(5)

                
                if panorama_mode and hand_sign_id == 2: 
                    if landmark_list[8][0] > point_history[-1][0]: 
                        view_start += view_shift_speed
                    else: 
                        view_start -= view_shift_speed


                if hand_sign_id == 2:  # 指差しサイン
                    point_history.append(landmark_list[8])  # 人差指座標
                else:
                    point_history.append([0, 0])

                # フィンガージェスチャー分類
                finger_gesture_id = 0
                point_history_len = len(pre_processed_point_history_list)
                if point_history_len == (history_length * 2):
                    finger_gesture_id = point_history_classifier(
                        pre_processed_point_history_list)

                # 直近検出の中で最多のジェスチャーIDを算出
                finger_gesture_history.append(finger_gesture_id)
                most_common_fg_id = Counter(
                    finger_gesture_history).most_common()

                # 描画
                debug_image = draw_bounding_rect(use_brect, debug_image, brect)
                debug_image = draw_landmarks(debug_image, landmark_list)
                debug_image = draw_info_text(
                    debug_image,
                    brect,
                    handedness,
                    keypoint_classifier_labels[hand_sign_id],
                    point_history_classifier_labels[most_common_fg_id[0][0]],
                )
        else:
            point_history.append([0, 0])

        debug_image = draw_info(debug_image, fps, mode, number)

        if panorama_mode: 
            view_width = 5000
            view_start = max(0, view_start)
            panorama_in_view = panorama[:,view_start:view_start+view_width]
            cv.imshow('Hand Gesture Recognition', panorama_in_view)
        elif drawing_mode: 
            h, w, c = debug_image.shape
            canvas = cv.resize(canvas, (w, h))
            canvas = draw_point_history(canvas, point_history)
            final = cv.addWeighted(canvas.astype('uint8'), 1, debug_image, 1, 0)
            cv.imshow('Hand Gesture Recognition', final)
        else: 
            # 画面反映 #############################################################
            cv.imshow('Hand Gesture Recognition', debug_image)

    cap.release()
    cv.destroyAllWindows()


if __name__ == '__main__':
    main()
