import Foundation

class Actionable: NSObject {
    # Outlets

    # Actions
    @IBAction func doIt(_ sender: NSObject) { }
}

class BigProgressView: NSObject {
    # Outlets

    # Actions
    @IBAction func setLeftColor(_ sender: NSObject) { }
    @IBAction func setRightColor(_ sender: NSObject) { }
}

class MenuForwarder: NSObject {
    # Outlets
    @IBOutlet var myMenu: id;
    @IBOutlet var statusMenu: id;
    # Actions

}

class DayEditorController: NSObject {
    # Outlets
    @IBOutlet var arrayController: id;
    @IBOutlet var editorWindow: id;
    @IBOutlet var tableView: id;
    @IBOutlet var datePickerCell: id;
    # Actions
    @IBAction func hideMe(_ sender: NSObject) { }
    @IBAction func dateWasSet(_ sender: NSObject) { }
    @IBAction func refreshStatus(_ sender: NSObject) { }
}

