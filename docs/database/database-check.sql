-- Run AFTER database-schema.sql on a disposable database:
-- psql -v ON_ERROR_STOP=1 -f docs/database/database-check.sql
-- Fixtures roll back. These checks validate DB constraints, not .NET authorization.
BEGIN;
DO $$
DECLARE
    u uuid := gen_random_uuid(); v uuid := gen_random_uuid();
    i uuid := gen_random_uuid(); j uuid := gen_random_uuid();
    p uuid := gen_random_uuid(); c uuid := gen_random_uuid(); c2 uuid := gen_random_uuid();
    o uuid := gen_random_uuid(); s uuid := gen_random_uuid(); img uuid := gen_random_uuid();
    msg uuid := gen_random_uuid();
BEGIN
    INSERT INTO app_users(id,auth_issuer,auth_subject,display_name) VALUES
      (u,'https://id.example.test','finder','Finder'),(v,'https://id.example.test','claimant','Claimant');
    INSERT INTO reception_points(id,name,public_address) VALUES(p,'Point','Public address');
    INSERT INTO items(id,posted_by,title,public_description,found_area,found_time_precision,custody_kind,holder_user_id)
      VALUES(i,u,'Bag','Blue bag','District','unknown','person',u),
            (j,u,'Keys','Three keys','District','unknown','person',u);
    BEGIN
      UPDATE items SET holder_point_id=p WHERE id=i;
      RAISE EXCEPTION 'Expected exactly one custody branch';
    EXCEPTION WHEN check_violation THEN NULL; END;
    BEGIN
      UPDATE items SET found_time_precision='range',found_from='2026-10-22',found_until='2026-10-21' WHERE id=i;
      RAISE EXCEPTION 'Expected invalid time range rejection';
    EXCEPTION WHEN check_violation THEN NULL; END;
    -- Zero questions still allows a claim.
    INSERT INTO claims(id,item_id,claimant_user_id,reviewer_user_id,source_custody_version)
      VALUES(c,i,v,u,1);
    BEGIN
      INSERT INTO conversations(claim_id) VALUES(c);
      RAISE EXCEPTION 'Expected pending claim chat rejection';
    EXCEPTION WHEN foreign_key_violation THEN NULL; END;
    UPDATE claims SET status='approved',decided_by=u,decided_at=now() WHERE id=c;
    INSERT INTO conversations(claim_id) VALUES(c);
    INSERT INTO verification_questions(item_id,slot,question_text) VALUES(i,1,'Color?'),(i,2,'Brand?'),(i,3,'Contents?');
    BEGIN
      INSERT INTO verification_questions(item_id,slot,question_text) VALUES(i,4,'Fourth?');
      RAISE EXCEPTION 'Expected fourth question rejection';
    EXCEPTION WHEN check_violation THEN NULL; END;
    INSERT INTO messages(id,conversation_id,sender_user_id,client_message_id,body) VALUES(gen_random_uuid(),c,v,msg,'Hello');
    BEGIN
      INSERT INTO messages(id,conversation_id,sender_user_id,client_message_id,body) VALUES(gen_random_uuid(),c,v,msg,'Retry');
      RAISE EXCEPTION 'Expected duplicate client message rejection';
    EXCEPTION WHEN unique_violation THEN NULL; END;
    INSERT INTO claims(id,item_id,claimant_user_id,reviewer_user_id,source_custody_version,status,decided_by,decided_at)
      VALUES(c2,j,v,u,1,'rejected',u,now());
    BEGIN
      INSERT INTO conversations(claim_id) VALUES(c2);
      RAISE EXCEPTION 'Expected rejected claim chat rejection';
    EXCEPTION WHEN foreign_key_violation THEN NULL; END;
    INSERT INTO custody_events(id,item_id,event_kind,custody_version,actor_user_id,claim_id,from_custody,occurred_at)
      VALUES(gen_random_uuid(),i,'returned',2,u,c,'{"kind":"person"}',now());
    BEGIN
      INSERT INTO custody_events(id,item_id,event_kind,custody_version,actor_user_id,from_custody,occurred_at)
        VALUES(gen_random_uuid(),i,'returned',3,u,'{"kind":"person"}',now());
      RAISE EXCEPTION 'Expected duplicate completed return rejection';
    EXCEPTION WHEN unique_violation THEN NULL; END;
    BEGIN
      INSERT INTO custody_events(id,item_id,event_kind,custody_version,actor_user_id,claim_id,from_custody,occurred_at)
        VALUES(gen_random_uuid(),j,'returned',2,u,c,'{"kind":"person"}',now());
      RAISE EXCEPTION 'Expected cross-item claim reference rejection';
    EXCEPTION WHEN foreign_key_violation THEN NULL; END;
    INSERT INTO stored_objects(id,owner_user_id,bucket,object_key,object_kind,expires_at)
      VALUES(o,u,'private','original/test','original',now()+interval '1 day'),
            (s,u,'private','sanitized/test','sanitized',now()+interval '1 day');
    INSERT INTO item_images(id,item_id,position,original_object_id) VALUES(img,i,1,o);
    BEGIN
      UPDATE item_images SET processing_state='ready' WHERE id=img;
      RAISE EXCEPTION 'Expected unreviewed image rejection';
    EXCEPTION WHEN check_violation THEN NULL; END;
    BEGIN
      UPDATE item_images SET sanitized_object_id=o WHERE id=img;
      RAISE EXCEPTION 'Expected original-as-sanitized rejection';
    EXCEPTION WHEN check_violation THEN NULL; END;
    BEGIN
      DELETE FROM stored_objects WHERE id=o;
      RAISE EXCEPTION 'Expected referenced object deletion rejection';
    EXCEPTION WHEN foreign_key_violation THEN NULL; END;
    BEGIN
      INSERT INTO ai_jobs(id,item_id,image_id,job_kind,source_version,source_sha256,model_id,model_revision,processing_profile,max_attempts)
      VALUES(gen_random_uuid(),j,img,'embed_image',1,repeat('a',64),'Qwen/Qwen3-VL-Embedding-2B','test-revision','test-profile',3);
      RAISE EXCEPTION 'Expected cross-item AI job rejection';
    EXCEPTION WHEN foreign_key_violation THEN NULL; END;
    BEGIN
      INSERT INTO ai_jobs(id,item_id,job_kind,source_version,source_sha256,model_id,model_revision,processing_profile,max_attempts,status)
      VALUES(gen_random_uuid(),i,'embed_text',1,repeat('a',64),'Qwen/Qwen3-VL-Embedding-2B','test-revision','test-profile',3,'running');
      RAISE EXCEPTION 'Expected running job without lease rejection';
    EXCEPTION WHEN check_violation THEN NULL; END;
    INSERT INTO item_embeddings(id,item_id,modality,source_version,source_sha256,model_id,model_revision,processing_profile,embedding)
      VALUES(gen_random_uuid(),i,'text',1,repeat('a',64),'Qwen/Qwen3-VL-Embedding-2B','test-revision','test-profile',array_fill(0.01::real,ARRAY[2048])::vector);
    IF (SELECT vector_dims(embedding) FROM item_embeddings WHERE item_id=i) <> 2048 THEN
      RAISE EXCEPTION 'Expected 2048 dimensions';
    END IF;
    BEGIN
      INSERT INTO item_embeddings(id,item_id,modality,source_version,source_sha256,model_id,model_revision,processing_profile,embedding)
      VALUES(gen_random_uuid(),j,'text',1,repeat('a',64),'Qwen/Qwen3-VL-Embedding-2B','test-revision','test-profile','[1,2,3]');
      RAISE EXCEPTION 'Expected wrong vector dimensions rejection';
    EXCEPTION WHEN data_exception THEN NULL; END;
    INSERT INTO idempotency_keys(actor_user_id,idempotency_key,operation,request_sha256,resource_type,resource_id,response_status)
      VALUES(u,msg,'create-item',repeat('b',64),'item',i,201);
    BEGIN
      INSERT INTO idempotency_keys(actor_user_id,idempotency_key,operation,request_sha256,resource_type,resource_id,response_status)
        VALUES(u,msg,'create-item',repeat('b',64),'item',i,201);
      RAISE EXCEPTION 'Expected duplicate idempotency key rejection';
    EXCEPTION WHEN unique_violation THEN NULL; END;
    RAISE NOTICE 'PASS: valid fixtures, zero-question claim, approved chat, 2048d vector, and 15 invalid cases rejected';
END $$;
ROLLBACK;
