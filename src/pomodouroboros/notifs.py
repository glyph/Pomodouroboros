from __future__ import annotations

from typing import Callable, Dict, Optional

from Foundation import NSError, NSObject

from UserNotifications import UNAuthorizationOptionNone, UNMutableNotificationContent, UNNotification, UNNotificationCategory, UNNotificationPresentationOptionBanner, UNNotificationRequest, UNNotificationResponse, UNTextInputNotificationAction, UNTextInputNotificationResponse, UNTimeIntervalNotificationTrigger, UNUserNotificationCenter


class NotificationDelegate(NSObject):
    def init(self) -> NotificationDelegate:
        self.handlers: Dict[str, Callable] = {}
        return self

    def userNotificationCenter_willPresentNotification_withCompletionHandler_(
        self,
        notificationCenter: UNUserNotificationCenter,
        notification: UNNotification,
        completionHandler: Callable,
    ) -> None:
        completionHandler(UNNotificationPresentationOptionBanner)

    def userNotificationCenter_didReceiveNotificationResponse_withCompletionHandler_(
        self,
        notificationCenter: UNUserNotificationCenter,
        notificationResponse: UNNotificationResponse,
        completionHandler: Callable,
    ) -> None:
        # technically only UNTextInputNotificationResponse has userText
        handler = self.handlers.pop(
            notificationResponse.notification().request().identifier(), None
        )
        if handler is not None:
            if isinstance(
                notificationResponse, UNTextInputNotificationResponse
            ):
                userText = notificationResponse.userText()
                handler(userText)

        completionHandler()


notificationCenter = UNUserNotificationCenter.currentNotificationCenter()
setIntentionCategoryIdentifier = "SET_INTENTION_PROMPT"
setIntentionMessageIdentifier = "ask-for-intent"
basicCategoryIdentifier = "BASIC_MESSAGE"
basicMessageIdentifier = "basic-message"


theDelegate = NotificationDelegate.alloc().init()


def askForIntent(callback: Callable[[str], None]):
    # When we ask for an intention, we should remove the reminder of the intention.
    notificationCenter.removeDeliveredNotificationsWithIdentifiers_(
        [basicMessageIdentifier]
    )
    theDelegate.handlers[setIntentionMessageIdentifier] = callback
    content = UNMutableNotificationContent.alloc().init()
    content.setTitle_("Time To Set Intention")
    content.setBody_("What do you want to do right now?")
    content.setCategoryIdentifier_(setIntentionCategoryIdentifier)
    trigger = (
        UNTimeIntervalNotificationTrigger.triggerWithTimeInterval_repeats_(
            1, False
        )
    )
    request = UNNotificationRequest.requestWithIdentifier_content_trigger_(
        setIntentionMessageIdentifier, content, trigger
    )

    def notificationRequestCompleted(error: Optional[NSError]) -> None:
        """
        Notification request completed, with an error passed if there was one.
        """
        # TODO: let the user know somehow if there was a problem

    notificationCenter.addNotificationRequest_withCompletionHandler_(
        request, notificationRequestCompleted
    )


def withdrawIntentPrompt() -> None:
    notificationCenter.removeDeliveredNotificationsWithIdentifiers_(
        [setIntentionMessageIdentifier]
    )


def notify(title="", subtitle="", informativeText=""):
    withdrawIntentPrompt()
    content = UNMutableNotificationContent.alloc().init()
    content.setTitle_(title)
    content.setSubtitle_(subtitle)
    content.setBody_(informativeText)

    trigger = (
        UNTimeIntervalNotificationTrigger.triggerWithTimeInterval_repeats_(
            1, False
        )
    )

    request = UNNotificationRequest.requestWithIdentifier_content_trigger_(
        basicMessageIdentifier, content, trigger
    )

    def notificationRequestCompleted(error: Optional[NSError]) -> None:
        """
        Notification request completed, with an error passed if there was one.
        """
        # TODO: let the user know somehow if there was a problem

    notificationCenter.addNotificationRequest_withCompletionHandler_(
        request, notificationRequestCompleted
    )


def setupNotifications():
    notificationCenter.setDelegate_(theDelegate)
    identifier = "SET_INTENTION"
    title = "Set Intention"
    options = 0
    # UNNotificationAction.actionWithIdentifier_title_options_(
    #     identifier, title, options
    # )
    textInputButtonTitle = "Set Intent"
    textInputPlaceholder = "What would you like to do?"
    setIntentionAction = UNTextInputNotificationAction.actionWithIdentifier_title_options_textInputButtonTitle_textInputPlaceholder_(
        identifier, title, options, textInputButtonTitle, textInputPlaceholder
    )
    options = 0
    actions = [setIntentionAction]
    # I think these are mostly to do with Siri
    intentIdentifiers = []
    setIntentionPromptCategory = UNNotificationCategory.categoryWithIdentifier_actions_intentIdentifiers_options_(
        setIntentionCategoryIdentifier, actions, intentIdentifiers, options
    )
    basicMessageCategory = UNNotificationCategory.categoryWithIdentifier_actions_intentIdentifiers_options_(
        basicCategoryIdentifier, [], [], 0
    )

    def completionHandler(granted: bool, error: NSError) -> None:
        """
        Authentication to display user notifications completed.
        """
        # TODO: somehow let the user know that they're not going to see
        # notifications if the permission wasn't granted

    notificationCenter.requestAuthorizationWithOptions_completionHandler_(
        UNAuthorizationOptionNone, completionHandler
    )
    notificationCenter.setNotificationCategories_(
        [basicMessageCategory, setIntentionPromptCategory]
    )
