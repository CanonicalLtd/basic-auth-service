"""Collection for Basic-Auth credentials."""

import asyncio
import logging

from .credential import (
    BasicAuthCredentials,
    hash_token256,
)
from .lock import locking
from .db import transact
from .api import ResourceCollection
from .api.sample import SampleResourceCollection
from .api.error import (
    ResourceAlreadyExists,
    ResourceNotFound,
    InvalidResourceDetails,
)


log = logging.getLogger()


class MemoryCredentialsCollection(SampleResourceCollection):
    """An in-memory Collection for Basic-Auth credentials."""

    # Valid credentials for API access.
    VALID_API_CREDENTIALS = ('user', 'pass')

    def __init__(self, loop=None):
        super().__init__(id_field='user')
        self.lock = asyncio.Lock(loop=loop)

    @locking
    async def create(self, details):
        token = _prep_token(details.get('token'))
        auth = _get_auth(token)
        self._check_duplicated_username(details['user'], auth.username)
        details['token'] = str(auth)
        return await super().create(details)

    async def get_all(self):
        """Return all credentials."""
        return await super().get_all()

    @locking
    async def update(self, user, details):
        token = _prep_token(details.get('token'))
        auth = _get_auth(token)
        self._check_duplicated_username(user, auth.username)
        details['token'] = str(auth)
        return await super().update(user, details)

    @locking
    async def delete(self, res_id):
        # wrap with locking
        return await super().delete(res_id)

    @locking
    async def get(self, res_id):
        # wrap with locking
        return await super().get(res_id)

    @locking
    async def credentials_match(self, username, password):
        """Return whether the provided user/password match."""
        credentials = [details['token'] for details in self.items.values()]
        return '{}:{}'.format(username, hash_token256(password)) in credentials

    async def api_credentials_match(self, username, password):
        """Return whether API credentials match."""
        return (username, password) == self.VALID_API_CREDENTIALS

    def _check_duplicated_username(self, user, username):
        """Raise InvalidResourceDetails if the username is already used."""
        for other_user, details in self.items.items():
            auth = BasicAuthCredentials.from_token(details['token'])
            if auth.username == username and user != other_user:
                raise InvalidResourceDetails('Token username already in use')


class DataBaseCredentialsCollection(ResourceCollection):
    """A database-backed resource Collection for Basic-Auth credentials."""

    def __init__(self, engine):
        self.engine = engine

    @transact
    async def create(self, model, details):
        """Create credentials for a user."""
        user = details['user']
        if await model.is_known_user(user):
            raise ResourceAlreadyExists(user)

        auth = _get_auth(details.get('token'))
        await self._check_duplicated_username(model, user, auth.username)
        await model.add_credentials(user, auth.username, auth.password)
        log.info('credentials added: {}'.format(user))
        return user, {'user': user, 'token': str(auth)}

    @transact
    async def get_all(self, model, start_date=None, end_date=None):
        """Return all credentials."""
        log.info('credentials listed')
        return (
            {'user': credentials.user, 'username': credentials.auth.username}
            for credentials in await model.get_all_credentials(
                start_date=start_date, end_date=end_date))

    @transact
    async def delete(self, model, user):
        """Delete credentials for a user."""
        removed = await model.remove_credentials(user)
        if removed:
            log.info('credentials deleted: {}'.format(user))
        else:
            raise ResourceNotFound(user)

    @transact
    async def get(self, model, user):
        """Return credentials for a user."""
        credentials = await model.get_credentials(user=user)
        if credentials is None:
            raise ResourceNotFound(user)
        log.info('credentials retrieved: {}'.format(user))
        return {'user': user, 'token': str(credentials.auth)}

    @transact
    async def update(self, model, user, details):
        """Update credentials for a user."""
        if not await model.is_known_user(user):
            raise ResourceNotFound(user)
        auth = _get_auth(details.get('token'))
        await self._check_duplicated_username(model, user, auth.username)
        await model.update_credentials(user, auth.username, auth.password)
        log.info('credentials updated: {}'.format(user))
        return {'user': user, 'token': str(auth)}

    @transact
    async def credentials_match(self, model, username, password):
        """Check if username and password match known credentials."""
        credentials = await model.get_credentials(username=username)
        if credentials is None:
            return False
        log.info('credentials login attempt: {}'.format(credentials.user))
        return credentials.password_match(password)

    @transact
    async def api_credentials_match(self, model, username, password):
        """Check if username and password match known API credentials."""
        credentials = await model.get_api_credentials(username)
        if credentials is None:
            return False
        return credentials.password_match(password)

    async def _check_duplicated_username(self, model, user, username):
        """Raise InvalidResourceDetails if the username is already used."""
        credentials = await model.get_credentials(username=username)
        if not credentials:
            return

        if credentials.user != user:
            # Another user is using this username.
            raise InvalidResourceDetails('Token username already in use')


def _prep_token(token):
    """Prepare a token by ensuring that it uses the hashword rather than
    the password.
    """
    if token is None:
        return
    split = token.split(':')
    if len(split) == 2 and '' not in split:
        split[1] = hash_token256(split[1])
        token = ':'.join(split)
    return token


def _get_auth(token):
    """Return BasicAuthCredentials from a token, generate them if None."""
    if token:
        # If present, the token is validated in its format, so this won't
        # fail.
        return BasicAuthCredentials.from_token(token)

    return BasicAuthCredentials.generate()
