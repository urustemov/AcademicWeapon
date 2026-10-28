/**
 * Secure JSON bridge used by advising.auca.kg.
 *
 * Add this file to the existing AAC Tracker Apps Script project. Store the
 * shared secret in Project Settings > Script properties as
 * AAC_TRACKER_API_KEY. The same value must be configured only in Render.
 */
function doPost(e) {
  const originalAssertAccess = assertAccess_;
  try {
    const body = JSON.parse((e && e.postData && e.postData.contents) || '{}');
    assertPortalApiKey_(body.apiKey);
    const portalActor = getPortalActor_(body.actorEmail);
    assertAccess_ = function() { return portalActor; };
    const payload = body.payload && typeof body.payload === 'object' ? body.payload : {};
    let data;

    switch (String(body.action || '')) {
      case 'bootstrap':
        data = getBootstrap();
        break;
      case 'searchStudents':
        data = searchStudents(payload.query);
        break;
      case 'getStudentProfile':
        data = getStudentProfile(payload.studentId);
        break;
      case 'saveVisit':
        data = saveVisit(payload);
        break;
      case 'getFollowUps':
        data = getFollowUps(payload.advisor, payload.bucket);
        break;
      case 'updateVisitStatus':
        data = updateVisitStatus(payload.rowNumber, payload.status);
        break;
      case 'getReport':
        data = getReport(payload);
        break;
      default:
        throw new Error('Unknown AAC Tracker action.');
    }

    return portalJson_({ok: true, data: data});
  } catch (error) {
    console.error('AAC Tracker portal request failed', error);
    return portalJson_({
      ok: false,
      error: String(error && error.message ? error.message : error)
    });
  } finally {
    assertAccess_ = originalAssertAccess;
  }
}

function assertPortalApiKey_(candidate) {
  const expected = PropertiesService.getScriptProperties().getProperty('AAC_TRACKER_API_KEY');
  if (!expected || String(candidate || '') !== expected) {
    throw new Error('Unauthorized AAC Tracker request.');
  }
}

function getPortalActor_(rawEmail) {
  const email = String(rawEmail || '').trim().toLowerCase();
  const advisor = CONFIG.ALLOWED_USERS[email] || '';
  if (!advisor) throw new Error('This account is not authorized to use AAC Tracker.');
  return {email: email, advisor: advisor, name: advisor, authorized: true};
}

function portalJson_(value) {
  return ContentService.createTextOutput(JSON.stringify(value))
    .setMimeType(ContentService.MimeType.JSON);
}
