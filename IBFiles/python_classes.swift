import Foundation

class Actionable: NSObject {
    # Outlets

    # Actions
    @IBAction func doIt(_ sender: NSObject) { }
}

class QuickApplication: NSObject {
    # Outlets

    # Actions

}

class HUDWindow: NSObject {
    # Outlets

    # Actions

}

class BigProgressView: NSObject {
    # Outlets

    # Actions
    @IBAction func setLeftColor(_ sender: NSObject) { }
    @IBAction func setRightColor(_ sender: NSObject) { }
}

class SessionDataSource: NSObject {
    # Outlets

    # Actions

}

class IntentionRow: NSObject {
    # Outlets

    # Actions
    @IBAction func estimateClicked(_ sender: NSObject) { }
}

class IntentionDataSource: NSObject {
    # Outlets

    # Actions

}

class StreakDataSource: NSObject {
    # Outlets

    # Actions

}

class PomFilesOwner: NSObject {
    # Outlets
    @IBOutlet var sessionDataSource: id;
    @IBOutlet var intentionDataSource: id;
    @IBOutlet var streakDataSource: id;
    @IBOutlet var intentionsWindow: id;
    @IBOutlet var intentionsTable: id;
    # Actions
    @IBAction func newIntentionClicked(_ sender: NSObject) { }
}

class HeightSizableTextField: NSObject {
    # Outlets

    # Actions

}

class PaddedTextFieldCell: NSObject {
    # Outlets

    # Actions

}

class MenuForwarder: NSObject {
    # Outlets
    @IBOutlet var myMenu: id;
    @IBOutlet var statusMenu: id;
    # Actions

}

class DescriptionChanger: NSObject {
    # Outlets

    # Actions

}

class DayEditorController: NSObject {
    # Outlets
    @IBOutlet var arrayController: id;
    @IBOutlet var editorWindow: id;
    @IBOutlet var tableView: id;
    @IBOutlet var datePickerCell: id;
    @IBOutlet var dayLabelField: id;
    # Actions
    @IBAction func hideMe(_ sender: NSObject) { }
    @IBAction func dateWasSet(_ sender: NSObject) { }
    @IBAction func refreshStatus(_ sender: NSObject) { }
}

class NotificationDelegate: NSObject {
    # Outlets

    # Actions

}

