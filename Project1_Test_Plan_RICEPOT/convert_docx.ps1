$word = New-Object -ComObject Word.Application
$word.Visible = $false
$doc = $word.Documents.Open("d:\AI Testing Course\AITestBlueprint\Project1_Test_Plan_RICEPOT\Product Requirements Document_ VWO Login Dashboard.docx")
$doc.SaveAs([ref]"d:\AI Testing Course\AITestBlueprint\Project1_Test_Plan_RICEPOT\PRD_VWO_temp.txt", [ref]2)
$doc.Close()
$word.Quit()
Write-Host "Conversion complete"
